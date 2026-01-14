import os
import shutil
from functools import cached_property
from pathlib import Path
from typing import List, Optional

from pyarrow import parquet

from ..common import logger
from .s3 import S3, S3Cfg, is_s3_path


class Files:
    """File operations for local file system and/or s3 protocol object stores."""

    def __init__(self, s3_cfg: Optional[S3Cfg] = None) -> None:
        self.s3_cfg = s3_cfg

    def mkdir(self, location: str | Path):
        """Create a directory or bucket if it doesn't already exist."""
        # make sure primary save location exists.
        if is_s3_path(location):
            # make sure bucket exists.
            bucket_name, _ = self.s3.bucket_and_partition(
                location, require_partition=False
            )
            self.s3.get_bucket(bucket_name)
        else:
            # make sure directory exists.
            Path(location).mkdir(exist_ok=True, parents=True)

    def copy(self, src_path: str | Path, dst_path: str | Path):
        """Copy file to a new location."""
        return self._transfer(src_path, dst_path, delete_src=False)

    def move(self, src_path: str | Path, dst_path: str | Path):
        """Move file to a new location."""
        return self._transfer(src_path, dst_path, delete_src=True)

    def delete(self, file: str | Path, if_exists: bool = False):
        """Delete file."""
        if is_s3_path(file):
            return self.s3.delete_file(file, if_exists=if_exists)
        try:
            Path(file).unlink()
        except FileNotFoundError:
            if not if_exists:
                raise

    def exists(self, file: str | Path) -> bool:
        """Returns True if file exists."""
        if is_s3_path(file):
            return self.s3.exists(file)
        return os.path.exists(file)

    def file_size(self, file: str | Path) -> int:
        """Returns file size in bytes."""
        if is_s3_path(file):
            return self.s3.file_size(file)
        return os.path.getsize(file)

    def list_files(
        self, directory: str | Path, pattern: Optional[str] = None
    ) -> List[Path] | List[str]:
        """Returns list of files in directory.

        Args:
            directory: Local directory path or S3 URI (e.g., "s3://bucket/prefix/")
            pattern: Optional glob pattern to filter files (e.g., "*.parquet")

        Examples:
            files.list_files("s3://my-bucket/data/", pattern="*.parquet")
            files.list_files("s3://my-bucket/data/*.json")  # pattern in path
        """
        if is_s3_path(directory):
            # If pattern provided separately, append to directory path
            s3_path = f"{str(directory).rstrip('/')}/{pattern}" if pattern else str(directory)
            return self.s3.list_files(s3_path)
        if pattern:
            return list(Path(directory).glob(pattern))
        return list(Path(directory).iterdir())

    def parquet_column_names(self, file: str | Path) -> List[str]:
        """Returns list of column names in parquet file."""
        return list(
            parquet.read_schema(
                file,
                filesystem=self.s3.arrow_fs() if is_s3_path(file) else None,
            ).names
        )

    @cached_property
    def s3(self) -> S3:
        return S3(self.s3_cfg)

    def _transfer(
        self,
        src_path: str | Path,
        dst_path: str | Path,
        delete_src: bool = False,
    ):
        """Move or copy file to a new location."""
        is_s3_move = False
        transfer_error = False

        try:
            if is_s3_path(src_path):
                if is_s3_path(dst_path):
                    is_s3_move = True
                    self.s3.move(
                        src_path=src_path, dst_path=dst_path, delete_src=delete_src
                    )
                else:
                    if os.path.isdir(dst_path):
                        dst_path = f"{dst_path}/{Path(src_path).name}"
                    # TODO make work with miltiple files.
                    try:
                        self.s3.download_file(
                            s3_path=src_path,
                            local_path=dst_path,
                            overwrite=True,
                        )
                    except Exception:
                        transfer_error = True
                        # Clean up partial local file on download error
                        if os.path.exists(dst_path):
                            try:
                                os.remove(dst_path)
                            except Exception as cleanup_err:
                                logger.warning(f"Failed to clean up partial file {dst_path}: {cleanup_err}")
                        raise

            elif is_s3_path(dst_path):
                # upload local file to s3.
                bucket_name, partition = self.s3.bucket_and_partition(
                    dst_path, require_partition=False
                )
                if not partition:
                    partition = str(src_path).split(f"{bucket_name}/")[-1].lstrip("/")
                try:
                    self.s3.client.upload_file(str(src_path), bucket_name, partition)
                except Exception:
                    transfer_error = True
                    # Clean up partial S3 object on upload error
                    try:
                        self.delete(dst_path, if_exists=True)
                    except Exception as cleanup_err:
                        logger.warning(f"Failed to clean up partial S3 object {dst_path}: {cleanup_err}")
                    raise
            else:
                try:
                    shutil.copy(src_path, dst_path)
                except Exception:
                    transfer_error = True
                    # Clean up partial destination file on copy error
                    if os.path.exists(dst_path):
                        try:
                            os.remove(dst_path)
                        except Exception as cleanup_err:
                            logger.warning(f"Failed to clean up partial file {dst_path}: {cleanup_err}")
                    raise

            if delete_src:
                if not is_s3_move and not self.exists(dst_path):
                    # would  already be checked for s3 move.
                    raise FileNotFoundError(f"Destination file {dst_path} does not exist after transfer")
                self.delete(src_path)
        finally:
            # Additional cleanup if error occurred and delete_src was requested
            # but source wasn't deleted yet (only applies if error in delete_src path)
            pass
