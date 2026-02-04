# files

[![PyPI version](https://img.shields.io/pypi/v/files.svg)](https://pypi.org/project/files/)
[![Python Versions](https://img.shields.io/pypi/pyversions/files.svg)](https://pypi.org/project/files/)
[![License](https://img.shields.io/github/license/dankelleher/files.svg)](https://github.com/dankelleher/files/blob/main/LICENSE)

A single high-level file operations API for seamlessly working with both local file systems and S3 protocol object stores.

## Overview

files provides a unified interface for common file operations, automatically handling the differences between local file systems and S3-compatible object stores. This makes it easy to write code that works with both types of storage without conditional logic.

**Key Features:**

- 🔄 Unified API for local and S3 operations
- 🔁 Automatic protocol detection
- 📁 File transfers between local and S3
- 🔍 List, find, and filter files
- 📊 Special support for data file formats (CSV, Parquet)
- 🧩 Utilities for compression and format conversion

## Quick Start

```python
from files import Files

# Create a Files instance
files = Files()

# Copy a file from local to S3
files.copy("/path/to/local/file.txt", "s3://my-bucket/file.txt")

# Copy a file from S3 to local
files.copy("s3://my-bucket/file.txt", "/path/to/local/file.txt")

# Check if a file exists (works with both local and S3)
exists = files.exists("s3://my-bucket/file.txt")

# List files (works with both local and S3)
file_list = files.list_files("/path/to/directory")
s3_file_list = files.list_files("s3://my-bucket/prefix")
```

## Documentation

### Core Functionality (`Files` class)

The `Files` class provides a high-level interface for file operations on both local and S3 storage.

```python
from files import Files

# Initialize with default S3 configuration
files = Files()

# Or with custom S3 configuration
from files import S3Cfg
s3_cfg = S3Cfg(
    aws_access_key_id="your-access-key",
    aws_secret_access_key="your-secret-key",
    s3_endpoint_url="https://your-endpoint",  # Optional
    s3_region="your-region"                  # Optional
)
files = Files(s3_cfg)
```

#### Available Methods

| Method | Description |
|--------|-------------|
| `create(location)` | Create a directory or bucket if it doesn't exist |
| `copy(src_path, dst_path)` | Copy a file from source to destination |
| `move(src_path, dst_path)` | Move a file from source to destination |
| `delete(file, if_exists=False)` | Delete a file, optionally only if it exists |
| `exists(file)` | Check if a file exists |
| `file_size(file)` | Get the size of a file in bytes |
| `list_files(directory, pattern=None)` | List files in a directory, optionally filtered by pattern |
| `parquet_column_names(file)` | Get column names from a parquet file |

### S3-Specific Functionality (`S3` class)

For operations specific to S3-compatible storage:

```python
from files import S3, S3Cfg

# Initialize with default S3 configuration from environment variables
s3 = S3()

# Or with custom configuration
s3_cfg = S3Cfg(
    aws_access_key_id="your-access-key",
    aws_secret_access_key="your-secret-key",
    s3_endpoint_url="https://your-endpoint",  # Optional
    s3_region="your-region"                  # Optional
)
s3 = S3(s3_cfg)
```

#### S3-Specific Methods

| Method | Description |
|--------|-------------|
| `upload(files, bucket_name, partition_relative_to=None)` | Upload local file(s) to S3 bucket |
| `read_file(path)` | Read a file from S3 into memory |
| `download_file(s3_path, local_path, overwrite=True)` | Download a file from S3 |
| `download_files(bucket_name, save_dir, partition=None, overwrite=True)` | Download files from a bucket/partition |
| `df_from_files(files)` | Create a pandas DataFrame from S3 files |
| `delete_file(file, if_exists=False)` | Delete a file from S3 |
| `delete_files(bucket_name, partition=None, if_exists=False)` | Delete files from a bucket/partition |
| `move(src_path, dst_path, delete_src)` | Move files within S3 |
| `exists(file)` | Check if a file or bucket exists |
| `file_size(file)` | Get the size of an S3 file |
| `get_bucket(bucket_name)` | Get or create an S3 bucket |
| `list_buckets(pattern=None)` | List all buckets, optionally filtered by pattern |
| `list_files(bucket_name, partition=None, return_as="urls", pattern=None)` | List files in a bucket/partition |

### Utility Functions

files includes several utility functions for working with files:

| Function | Description |
|----------|-------------|
| `gzip_file(file, suffix=".csv.gz", delete=True)` | Compress a file with gzip |
| `gzip_files(files, suffix=".csv.gz", delete=True, n_proc=4)` | Compress multiple files in parallel |
| `csvs_to_parquet(files, header, save_path_generator=with_parquet_extension)` | Convert CSV files to Parquet format |
| `csv_to_parquet(file, header, save_path_generator=with_parquet_extension)` | Convert a single CSV file to Parquet |

## Configuration

The `S3Cfg` class allows you to configure S3 credentials and connection parameters:

```python
from files import S3Cfg

s3_cfg = S3Cfg(
    aws_access_key_id="your-access-key",
    aws_secret_access_key="your-secret-key",
    s3_endpoint_url="https://your-endpoint",  # Optional, defaults to AWS S3
    s3_region="your-region",                 # Optional
    aws_zone_bucket_suffix=None              # Optional, for AWS One Zone buckets
)
```

If not provided, configuration values will be loaded from environment variables with the same names.

## Examples

### Working with Local Files

```python
from files import Files
from pathlib import Path

files = Files()

# Create directories
files.create("data/output")

# Copy files
files.copy("data/input.txt", "data/output/input_copy.txt")

# Move files
files.move("data/temp.txt", "data/output/temp.txt")

# Check file existence
if files.exists("data/output/input_copy.txt"):
    print(f"File size: {files.file_size('data/output/input_copy.txt')} bytes")

# List files
for file in files.list_files("data/output", "*.txt"):
    print(f"Found file: {file}")

# Delete files
files.delete("data/output/temp.txt")
```

### Working with S3

```python
from files import Files, S3Cfg

# Configure S3 with custom endpoint (e.g., MinIO)
s3_cfg = S3Cfg(
    aws_access_key_id="minioadmin",
    aws_secret_access_key="minioadmin",
    s3_endpoint_url="http://localhost:9000"
)
files = Files(s3_cfg)

# Create a bucket
files.create("s3://test-bucket")

# Upload a local file to S3
files.copy("data/test.csv", "s3://test-bucket/data/test.csv")

# List files in the bucket
s3_files = files.list_files("s3://test-bucket")
for file in s3_files:
    print(f"S3 file: {file}")

# Download a file from S3
files.copy("s3://test-bucket/data/test.csv", "data/test_from_s3.csv")

# Delete a file from S3
files.delete("s3://test-bucket/data/test.csv")
```

### Converting and Processing Files

```python
from files import csvs_to_parquet, gzip_files
from pathlib import Path

# Compress multiple CSV files
csv_files = list(Path("data").glob("*.csv"))
gzip_files(csv_files)

# Convert compressed CSV files to Parquet
compressed_files = list(Path("data").glob("*.csv.gz"))
csvs_to_parquet(compressed_files, header=True)
```

### Direct S3 Operations

```python
from files import S3, S3Cfg

# Initialize S3 client
s3_cfg = S3Cfg(
    aws_access_key_id="your-access-key",
    aws_secret_access_key="your-secret-key"
)
s3 = S3(s3_cfg)

# List all buckets
buckets = s3.list_buckets()
print(f"Available buckets: {buckets}")

# Upload multiple files with a partition structure
import glob
local_files = glob.glob("data/logs/*.log")
s3.upload(local_files, "logs-bucket", partition_relative_to="data")

# Download all files from a specific partition
s3.download_files("logs-bucket", "downloaded_logs", partition="logs/2023")

# Create a pandas DataFrame directly from S3 parquet files
import pandas as pd
files = s3.list_files("my-data-bucket", pattern="*.parquet")
df = s3.df_from_files(files)
print(df.head())
```

## Working with DuckDB and S3

files provides integration with DuckDB for efficient data processing:

```python
import duckdb
from files import S3Cfg, create_duckdb_secret

# Create a DuckDB connection
con = duckdb.connect("my_database.db")

# Configure S3 access for DuckDB
s3_cfg = S3Cfg(
    aws_access_key_id="your-access-key",
    aws_secret_access_key="your-secret-key",
    s3_endpoint_url="https://your-endpoint"
)
create_duckdb_secret(s3_cfg, secret_name="my_s3_config", conn=con)

# Query S3 data directly with DuckDB
query = """
SELECT *
FROM read_parquet('s3://my-bucket/data/*.parquet')
LIMIT 10;
"""
df = con.execute(query).fetchdf()
print(df)
```

## Environment Variables

files uses these environment variables if not explicitly configured:

- `AWS_ACCESS_KEY_ID` - S3 access key
- `AWS_SECRET_ACCESS_KEY` - S3 secret key
- `S3_REGION` - S3 region (optional)
- `S3_ENDPOINT_URL` - S3 endpoint URL (optional, defaults to AWS)

## License

MIT

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.
