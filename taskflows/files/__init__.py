from .core import Files
from .s3 import S3, S3Cfg, create_duckdb_secret, is_s3_path
from .utils import (
    csv_to_parquet,
    csvs_to_parquet,
    gzip_file,
    gzip_files,
    pprint_bytes,
    with_parquet_extension,
)

__all__ = [
    "S3",
    "Files",
    "S3Cfg",
    "create_duckdb_secret",
    "csv_to_parquet",
    "csvs_to_parquet",
    "gzip_file",
    "gzip_files",
    "is_s3_path",
    "pprint_bytes",
    "with_parquet_extension",
]
