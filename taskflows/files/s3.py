import fnmatch
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from functools import cached_property
from io import BytesIO
from pathlib import Path
from time import sleep
from typing import Generator, List, Literal, Optional, Sequence, Tuple, Union

import boto3
import duckdb
import pandas as pd
from boto3.session import Config
from botocore.exceptions import ClientError
from duckdb import DuckDBPyConnection
from pyarrow.fs import S3FileSystem
from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings
from xxhash import xxh32

from .extensions import file_extensions_re
from .utils import logger

PathT = Union[str | Path]

S3Locations = Literal["local", "backblaze", "aws"]


http_re = re.compile(r"^https?://")


class S3Cfg(BaseSettings):
    """S3 configuration. Variables will be loaded from environment variables if set."""

    aws_access_key_id: str
    aws_secret_access_key: SecretStr
    s3_region: Optional[str] = None
    s3_endpoint_url: Optional[str] = None
    # AWS One Zone Availability Zone suffix. e.g. --use1-az6--x-s3
    aws_zone_bucket_suffix: Optional[str] = None  # not yet supported with boto3

    @field_validator("s3_endpoint_url")
    @classmethod
    def ensure_url_has_scheme(cls, v: Optional[str]) -> Optional[str]:
        if v and not http_re.match(v):
            return f"https://{v}"
        return v


def get_s3_cfg(save_loc: S3Locations) -> S3Cfg:
    if save_loc == "backblaze":
        return S3Cfg(
            aws_access_key_id=os.getenv("BB_AWS_ACCESS_KEY_ID"),
            aws_secret_access_key=os.getenv("BB_AWS_SECRET_ACCESS_KEY"),
            s3_endpoint_url=os.getenv("BB_S3_ENDPOINT"),
            s3_region="us-east-005",
        )
    if save_loc == "local":
        return S3Cfg(
            aws_access_key_id=os.getenv("LOCAL_AWS_ACCESS_KEY_ID"),
            aws_secret_access_key=os.getenv("LOCAL_AWS_SECRET_ACCESS_KEY"),
            s3_endpoint_url=os.getenv("LOCAL_S3_ENDPOINT"),
        )
    if save_loc == "aws":
        return S3Cfg(
            aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
            aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
            s3_endpoint_url=os.getenv("AWS_S3_ENDPOINT"),
            s3_region=os.environ["AWS_S3_REGION"],
        )
    raise ValueError(f"Invalid save location: {save_loc}")


def is_s3_path(path: PathT) -> bool:
    """Returns True if `path` is an s3 path."""
    return str(path).startswith("s3://")


def create_duckdb_secret(
    s3: Optional[S3Cfg | S3Locations] = None,
    secret_name: Optional[str] = None,
    conn: Optional[DuckDBPyConnection] = None,
):
    """
    Create a duckdb secret with the given `s3`, `secret_name`, and `conn`.

    Args:
    - s3: S3 configuration or S3 location. If None, uses default S3Cfg.
    - secret_name: Name of the secret to create. If None, generates a unique name.
    - conn: duckdb connection. If None, uses default duckdb connection.
    """
    if not s3:
        s3_cfg = S3Cfg()
    elif isinstance(s3, str):
        s3_cfg = get_s3_cfg(s3)
    else:
        s3_cfg = s3
    conn = conn or duckdb
    secret = [
        "TYPE S3",
        f"KEY_ID '{s3_cfg.aws_access_key_id}'",
        f"SECRET '{s3_cfg.aws_secret_access_key.get_secret_value()}'",
    ]
    if s3_cfg.s3_endpoint_url is not None:
        secret += [
            f"ENDPOINT '{http_re.sub('', s3_cfg.s3_endpoint_url).rstrip('/')}'",
            f"USE_SSL {not s3_cfg.s3_endpoint_url.startswith('http://')}",
        ]
        if http_re.match(s3_cfg.s3_endpoint_url):
            secret.append("URL_STYLE path")
    if s3_cfg.s3_region:
        secret.append(f"REGION '{s3_cfg.s3_region}'")
    secret = ",".join(secret)
    if secret_name is None:
        secret_id = xxh32(secret.encode()).hexdigest()
        secret_name = f"files_s3_{secret_id}"
    conn.execute(f"CREATE SECRET IF NOT EXISTS {secret_name} ({secret});")


class S3:
    """File operations for s3 protocol object stores."""

    _bucket_and_partition_re = re.compile(r"s3:\/\/([a-zA-Z0-9.\-_]{1,255})(?:\/(.+))?")

    def __init__(self, s3_cfg: Optional[S3Cfg] = None) -> None:
        self.cfg = s3_cfg or S3Cfg()

    def upload(
        self,
        files: PathT | Sequence[PathT],
        bucket_name: str,
        partition_relative_to: Optional[str] = None,
    ):
        """Upload a local file or files to a bucket.

        Args:
            files (Union[PathT, Sequence[PathT]]): Local file or files to upload. (Note: easily get list of local files via `Path.glob`, `Path.rglob`, or `Path.iterdir`)
            bucket_name (str): Bucket to upload to.
            partition_relative_to (Optional[str], optional): Use part of `file` path relative to `partition_relative_to` as s3 partition. If literal "bucket_name", path relative to `bucket_name` arg will be used. Defaults to None.
        """
        files = [files] if isinstance(files, str) else files
        for file in files:
            partition = (
                str(file).split(partition_relative_to)[-1].lstrip("/")
                if partition_relative_to
                else file
            )
            logger.info(f"Uploading {file} to s3://{bucket_name}/{partition}")
            self.client.upload_file(str(file), bucket_name, partition)

    def read_file(self, path: str) -> BytesIO:
        """Read a file from s3.

        Args:
            path (str): Path in S3.

        Returns:
            BytesIO: The downloaded file contents.
        """
        bucket_name, partition = self.bucket_and_partition(path)
        buffer = BytesIO()
        self.client.download_fileobj(bucket_name, partition, buffer)
        buffer.seek(0)
        return buffer

    def download_file(
        self,
        s3_path: str,
        local_path: PathT,
        overwrite: bool = True,
        max_retries: int = 1,
        retry_delay: float = 0.5,
    ) -> bool:
        """Download a file from s3.

        Args:
            s3_path (str): The file to download.
            local_path (PathT): A local file path or directory to save the file to. If a directory is provided, any subdirectories in `s3_path` partition will be created with the `local_path` as the root.
            overwrite (bool, optional): Overwrite file if it already exists. Defaults to True.

        Returns:
            bool: True if file was downloaded, False if file already exists and `overwrite` is False.
        """
        local_path = Path(local_path)
        if not local_path.suffix:
            # this is a directory.
            local_path = local_path.joinpath(s3_path.replace("s3://", ""))
        local_path.parent.mkdir(exist_ok=True, parents=True)
        if local_path.exists() and not overwrite:
            logger.info(f"File {local_path} already exists. Skipping download.")
            return False
        bucket, partition = self.bucket_and_partition(s3_path)
        for attempt in range(max_retries + 1):
            try:
                self.client.download_file(bucket, partition, str(local_path))
                # with local_path.open(mode="wb+") as f:
                #    self.client.download_fileobj(bucket, partition, f)
                # Check if file was downloaded and is not empty
                if not local_path.exists():
                    raise FileNotFoundError(
                        f"Downloaded file {local_path} does not exist"
                    )
                st_size = local_path.stat().st_size
                if st_size == 0:
                    raise ValueError(f"Downloaded file {local_path} is empty")
                logger.info(f"Successfully downloaded {local_path} ({st_size} bytes)")
                return True
            except Exception as e:
                logger.warning(
                    f"Failed to download s3://{bucket}/{partition} on attempt {attempt + 1}: {e}"
                )
                # Remove potentially corrupted file
                if local_path.exists():
                    local_path.unlink()
                logger.info(f"Retrying in {retry_delay} seconds...")
                sleep(retry_delay)
        logger.error(
            f"Failed to download {local_path} after {max_retries + 1} attempts"
        )
        return False

    def download_files(
        self,
        s3_path: str,
        save_dir: Path,
        overwrite: bool = True,
        max_workers: int = 10,
    ):
        """Download files from s3 in parallel.

        Args:
            s3_path (str): S3 URI in format s3://bucket/prefix/pattern* where pattern can be any valid glob pattern.
            save_dir (Path): Local directory where files should be downloaded to.
            overwrite (bool, optional): Overwrite existing local files. Defaults to True.
            max_workers (int, optional): Maximum number of parallel downloads. Defaults to 10.
        """
        files = self.list_files(s3_path, return_as="urls")

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(self.download_file, file, save_dir, overwrite): file
                for file in files
            }
            for future in as_completed(futures):
                file = futures[future]
                try:
                    future.result()
                except Exception as e:
                    logger.error(f"Failed to download {file}: {e}")

    def df_from_files(self, files: Sequence[str]) -> pd.DataFrame:
        if isinstance(files, str):
            files = [files]
        with duckdb.connect() as con:
            create_duckdb_secret(
                s3=self.cfg,
                conn=con,
            )
            files = ",".join([f"'{f}'" for f in files])
            df = con.execute(f"""SELECT * FROM read_parquet({files})""").df()
        return df

    def delete_file(self, file: str, if_exists: bool = False):
        """Delete a file from s3.

        Args:
            file (str): URL of file in s3.
            if_exists (bool, optional): Do not raise exception if file does not exist. Defaults to False.
        """
        bucket_name, partition = self.bucket_and_partition(file)
        try:
            self.client.delete_object(
                Bucket=bucket_name,
                Key=partition,
            )
        except ClientError as err:
            if err.response["Error"]["Code"] == "404":
                if not if_exists:
                    raise err
            else:
                raise err

    def delete_files(
        self, s3_path: str, if_exists: bool = False
    ):
        """Delete files matching an S3 path with optional glob pattern.

        Args:
            s3_path (str): S3 URI in format s3://bucket/prefix/pattern* where pattern can be any valid glob pattern.
            if_exists (bool, optional): Do not raise exception if file does not exist. Defaults to False.
        """
        bucket_name, _ = self.bucket_and_partition(s3_path, require_partition=False)
        files = self.list_files(s3_path, return_as="paths")

        for i in range(0, len(files), 1000):
            batch = files[i:i + 1000]
            try:
                self.client.delete_objects(
                    Bucket=bucket_name,
                    Delete={"Objects": [{"Key": key} for key in batch]},
                )
            except ClientError as err:
                if err.response["Error"]["Code"] == "404":
                    if not if_exists:
                        raise err
                else:
                    raise err

    def move(self, src_path: str, dst_path: str, delete_src: bool):
        """Move files in s3 to another location in s3.
            - move a file to new partition
            - move a file to a new file
            - move a partition to a new partition
        Args:
            src_path (str): Source S3 URI (can include glob pattern).
            dst_path (str): Destination S3 URI.
            delete_src (bool): Remove the content at src_path after transferring.
        """
        src_bucket_name, _ = self.bucket_and_partition(
            src_path, require_partition=False
        )
        dst_bucket_name, dst_partition = self.bucket_and_partition(
            dst_path, require_partition=False
        )

        src_files = self.list_files(src_path, return_as="paths")

        src_partition_is_file = self.is_file_path(src_path)
        dst_partition_is_file = self.is_file_path(dst_path)

        if src_partition_is_file:
            assert len(src_files) == 1
            
        elif dst_partition_is_file:
            raise ValueError(
                f"Cannot move a partition to a file. Partition: {src_path}, File: {dst_path}"
            )
        
        copied_files = []
        for src_file in src_files:
            dst_key = f"{dst_partition}/{src_file.split('/')[-1]}"
            logger.info(f"Moving {src_file} to {dst_key}")
            self.client.copy_object(
                CopySource={"Bucket": src_bucket_name, "Key": src_file},
                Bucket=dst_bucket_name,
                Key=dst_key,
            )
            copied_files.append(src_file)

        if delete_src and copied_files:
            # Verify destination file exists before deleting source
            if src_partition_is_file:
                dst_file_path = f"s3://{dst_bucket_name}/{dst_key}"
                if not self.exists(dst_file_path):
                    raise FileNotFoundError(f"Destination file does not exist: {dst_file_path}")

            logger.info(f"Deleting {len(copied_files)} source files from {src_bucket_name}")
            for i in range(0, len(copied_files), 1000):
                batch = copied_files[i:i + 1000]
                self.client.delete_objects(
                    Bucket=src_bucket_name,
                    Delete={"Objects": [{"Key": key} for key in batch]},
                )

    def exists(self, file: str) -> bool:
        """Check if a file exists in s3."""
        bucket, partition = self.bucket_and_partition(file, require_partition=False)
        if not partition:
            # check if bucket exists.
            try:
                self.client.head_bucket(Bucket=bucket)
                return True
            except ClientError as e:
                if e.response["Error"]["Code"] == "404":
                    # The bucket does not exist.
                    return False
                raise
        try:
            self.client.head_object(Bucket=bucket, Key=partition)
            return True
        except ClientError as e:
            if e.response["Error"]["Code"] == "404":
                # The object does not exist.
                return False
            raise

    def file_size(self, file: str) -> int:
        """Get the size of a file in bytes."""
        bucket, partition = self.bucket_and_partition(file)
        return self.resource.Object(bucket, partition).content_length

    def get_bucket(self, bucket_name: str) -> "Bucket":
        """Get a bucket object for `bucket_name`. If bucket does not exist, create it."""
        if self.cfg.s3_endpoint_url and "s3express-" in self.cfg.s3_endpoint_url:
            logger.warning(
                f"AWS One Zone buckets are not supported. Can not get bucket. If bucket '{bucket_name}' needs to be created, please create it manually via the AWS console or CLI."
            )
            return
        bucket_name = re.sub(r"^s3:\/\/", "", bucket_name)
        bucket = self.resource.Bucket(bucket_name)
        if not bucket.creation_date:
            try:
                logger.info(f"Creating new bucket: {bucket_name}")
                CreateBucketConfiguration = {}
                # us-east-1 is the default region and doesn't accept LocationConstraint
                if self.cfg.s3_region and self.cfg.s3_region != "us-east-1":
                    CreateBucketConfiguration["LocationConstraint"] = self.cfg.s3_region
                """
                if self.cfg.aws_zone_bucket_suffix.endswith('--x-s3'):
                    CreateBucketConfiguration['Location'] = {
                        'Type': 'AvailabilityZone',
                        'Name': 'use1-az6'
                    }
                    CreateBucketConfiguration['Bucket'] = {
                        'DataRedundancy': 'SingleAvailabilityZone',
                        'Type': 'Directory'
                    }
                """
                if CreateBucketConfiguration:
                    bucket.create(
                        CreateBucketConfiguration=CreateBucketConfiguration
                    )
                else:
                    bucket.create()
            except ClientError as err:
                if err.response["Error"]["Code"] != "BucketAlreadyOwnedByYou":
                    raise err
        return bucket

    def list_buckets(self, pattern: Optional[str] = None) -> List[str]:
        """Names of all buckets on server. Optionally keep only buckets matching `pattern`."""
        buckets = [b["Name"] for b in self.client.list_buckets()["Buckets"]]
        if pattern:
            return fnmatch.filter(buckets, pattern)
        return buckets

    def list_files(
        self,
        s3_path: str,
        return_as: Literal["names", "paths", "urls", "obj"] = "urls",
    ) -> List[str]:
        """List files matching an S3 path with optional glob pattern.

        Args:
            s3_path (str): S3 URI in format s3://bucket/prefix/pattern* where pattern can be any valid glob pattern.
            return_as (Literal["names", "paths", "urls", "obj"], optional): How files should be returned. Defaults to "urls".

        Examples:
            s3.list_files("s3://my-bucket/data/*.parquet")
            s3.list_files("s3://my-bucket/data/2024-*/file_*.json")
            s3.list_files("s3://my-bucket/data/")
        """
        bucket_name, prefix, pattern = self.parse_s3_path(s3_path)

        paginator = self.client.get_paginator("list_objects_v2")
        page_kwargs = {"Bucket": bucket_name}
        if prefix:
            page_kwargs["Prefix"] = prefix

        files = []
        for page in paginator.paginate(**page_kwargs):
            if "Contents" not in page:
                continue
            for obj in page["Contents"]:
                if pattern and not fnmatch.fnmatch(obj["Key"], pattern):
                    continue
                files.append(obj)

        if return_as != "obj":
            files = [obj["Key"] for obj in files]
            if return_as == "urls":
                files = [f"s3://{bucket_name}/{f}" for f in files]
            if return_as == "names":
                files = [f.split("/")[-1] for f in files]

        return files

    def list_file_pages(
        self,
        s3_path: str,
        return_as: Literal["names", "paths", "urls", "obj"] = "urls",
    ) -> Generator[List[str], None, None]:
        """List files matching an S3 path with optional glob pattern, yielding one page at a time.

        Args:
            s3_path (str): S3 URI in format s3://bucket/prefix/pattern* where pattern can be any valid glob pattern.
            return_as (Literal["names", "paths", "urls", "obj"], optional): How files should be returned. Defaults to "urls".

        Examples:
            for page in s3.list_file_pages("s3://my-bucket/data/*.parquet"):
                process(page)
        """
        bucket_name, prefix, pattern = self.parse_s3_path(s3_path)

        paginator = self.client.get_paginator("list_objects_v2")
        page_kwargs = {"Bucket": bucket_name}
        if prefix:
            page_kwargs["Prefix"] = prefix

        for page in paginator.paginate(**page_kwargs):
            if "Contents" not in page:
                continue
            page_files = []
            for obj in page["Contents"]:
                if pattern and not fnmatch.fnmatch(obj["Key"], pattern):
                    continue
                page_files.append(obj)

            if page_files:  # Only yield if there are files after filtering
                if return_as != "obj":
                    page_files = [obj["Key"] for obj in page_files]
                    if return_as == "urls":
                        page_files = [f"s3://{bucket_name}/{f}" for f in page_files]
                    if return_as == "names":
                        page_files = [f.split("/")[-1] for f in page_files]
                yield page_files
    def bucket_and_partition(
        self, path: str, require_partition: bool = False
    ) -> None | Tuple[str, str]:
        """Split a s3 path into bucket and partition."""
        if match := self._bucket_and_partition_re.search(path):
            # bucket name, partition
            bucket = match.group(1)
            partition = match.group(2)
            if require_partition and not partition:
                raise ValueError(f"Path {path} does not contain a partition: {path}")
            return bucket, partition
        return None, None

    def parse_s3_path(
        self, s3_path: str
    ) -> Tuple[str, str, Optional[str]]:
        """Parse S3 path into bucket, prefix, and optional glob pattern.

        Args:
            s3_path: S3 URI like s3://bucket/prefix/pattern*

        Returns:
            Tuple of (bucket_name, prefix, pattern) where pattern is None if no glob chars found
        """
        bucket_name, path = self.bucket_and_partition(s3_path, require_partition=False)

        prefix = ""
        pattern = None

        if path:
            # Find where the glob pattern starts
            glob_chars = {'*', '?'}
            glob_start_idx = next((i for i, char in enumerate(path) if char in glob_chars), len(path))

            if glob_start_idx < len(path):
                # There's a glob pattern
                # The prefix is everything up to the last '/' before the glob
                prefix_end = path.rfind('/', 0, glob_start_idx)
                if prefix_end != -1:
                    prefix = path[:prefix_end + 1]
                    pattern = path
                else:
                    # Glob starts at the beginning
                    pattern = path
            else:
                # No glob pattern, entire path is prefix
                prefix = path

        return bucket_name, prefix, pattern

    def is_file_path(self, path: str) -> bool:
        """Return True if provided path is to a file."""
        if file_extensions_re.search(path):
            # path has a known file extension.
            return True
        bucket_name, partition = self.bucket_and_partition(path)
        try:
            # Check if the path is a file
            self.client.head_object(Bucket=bucket_name, Key=partition)
            return True
        except self.client.exceptions.ClientError:
            return False

    @cached_property
    def arrow_fs(self) -> "S3FileSystem":
        kwargs = dict(
            access_key=self.cfg.aws_access_key_id,
            secret_key=self.cfg.aws_secret_access_key.get_secret_value(),
        )
        if self.cfg.s3_endpoint_url:
            kwargs["endpoint_override"] = self.cfg.s3_endpoint_url
        if self.cfg.s3_region:
            kwargs["region"] = self.cfg.s3_region
        return S3FileSystem(**kwargs)

    @cached_property
    def resource(self):
        return self._boto3_obj("resource")

    @cached_property
    def client(self):
        return self._boto3_obj("client")

    def _boto3_obj(self, obj_type: Literal["resource", "client"]):
        kwargs = dict(
            aws_access_key_id=self.cfg.aws_access_key_id,
            aws_secret_access_key=self.cfg.aws_secret_access_key.get_secret_value(),
            config=Config(signature_version="s3v4"),
        )
        if self.cfg.s3_endpoint_url:
            kwargs["endpoint_url"] = self.cfg.s3_endpoint_url
        if self.cfg.s3_region:
            kwargs["region_name"] = self.cfg.s3_region
        return getattr(boto3, obj_type)("s3", **kwargs)
