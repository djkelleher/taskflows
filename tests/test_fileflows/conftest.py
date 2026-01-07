import os
import shutil
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import boto3
import pandas as pd
import pytest
from taskflows.files.s3 import S3, S3Cfg
from moto import mock_aws


@pytest.fixture
def temp_dir():
    """Create a temporary directory for test files."""
    dir_path = tempfile.mkdtemp()
    yield Path(dir_path)
    shutil.rmtree(dir_path)


@pytest.fixture
def sample_file(temp_dir):
    """Create a sample text file for testing."""
    file_path = temp_dir / "sample.txt"
    with open(file_path, "w") as f:
        f.write("This is a test file.")
    return file_path


@pytest.fixture
def sample_csv_file(temp_dir):
    """Create a sample CSV file for testing."""
    file_path = temp_dir / "sample.csv"
    df = pd.DataFrame({"A": [1, 2, 3], "B": [4, 5, 6]})
    df.to_csv(file_path, index=False)
    return file_path


@pytest.fixture
def sample_parquet_file(temp_dir):
    """Create a sample Parquet file for testing."""
    file_path = temp_dir / "sample.parquet"
    df = pd.DataFrame({"A": [1, 2, 3], "B": [4, 5, 6]})
    df.to_parquet(file_path, index=False)
    return file_path


@pytest.fixture
def mock_s3_client():
    """Mock the S3 client."""
    with mock_aws():
        # Create a real boto3 client to use with moto
        s3_client = boto3.client(
            "s3",
            aws_access_key_id="test",
            aws_secret_access_key="test",
            region_name="us-east-1",
        )
        yield s3_client


@pytest.fixture
def mock_s3_resource():
    """Mock the S3 resource."""
    with mock_aws():
        # Create a real boto3 resource to use with moto
        s3_resource = boto3.resource(
            "s3",
            aws_access_key_id="test",
            aws_secret_access_key="test",
            region_name="us-east-1",
        )
        yield s3_resource


@pytest.fixture
def mock_s3_bucket(mock_s3_client):
    """Create a mock S3 bucket for testing."""
    bucket_name = "test-bucket"
    mock_s3_client.create_bucket(Bucket=bucket_name)
    return bucket_name


@pytest.fixture
def s3_cfg():
    """Create a mock S3Cfg for testing."""
    return S3Cfg(
        aws_access_key_id="test",
        aws_secret_access_key="test",
        s3_endpoint_url="http://localhost:9000",
        s3_region="us-east-1",
    )


@pytest.fixture
def s3_client(s3_cfg):
    """Create an S3 client with mocked credentials."""
    with patch.object(S3, "_boto3_obj", return_value=MagicMock()):
        s3 = S3(s3_cfg)
        yield s3
        yield s3
