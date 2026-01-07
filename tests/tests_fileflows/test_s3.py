from io import BytesIO
from pathlib import Path
from unittest.mock import MagicMock, patch

import boto3
import pandas as pd
import pytest
from botocore.exceptions import ClientError
from files.s3 import S3, S3Cfg, create_duckdb_secret, is_s3_path
from moto import mock_aws


def test_is_s3_path():
    """Test is_s3_path function."""
    assert is_s3_path("s3://bucket/key")
    assert not is_s3_path("/local/path")


def test_create_duckdb_secret():
    """Test create_duckdb_secret function with mocked duckdb."""
    mock_conn = MagicMock()
    s3_cfg = S3Cfg(
        aws_access_key_id="test",
        aws_secret_access_key="test",
        s3_endpoint_url="http://localhost:9000",
    )

    create_duckdb_secret(s3_cfg, "test_secret", mock_conn)
    mock_conn.execute.assert_called_once()


def test_s3_bucket_and_partition():
    """Test bucket_and_partition method."""
    s3 = S3(S3Cfg(aws_access_key_id="test", aws_secret_access_key="test"))

    # Test with valid S3 path with partition
    bucket, partition = s3.bucket_and_partition("s3://bucket/key/path")
    assert bucket == "bucket"
    assert partition == "key/path"

    # Test with valid S3 path without partition
    bucket, partition = s3.bucket_and_partition("s3://bucket", require_partition=False)
    assert bucket == "bucket"
    assert partition is None

    # Test with invalid S3 path (should return None, None)
    bucket, partition = s3.bucket_and_partition("invalid-path", require_partition=False)
    assert bucket is None
    assert partition is None

    # Test with S3 path requiring partition but none provided
    with pytest.raises(ValueError):
        s3.bucket_and_partition("s3://bucket", require_partition=True)


def test_is_file_path():
    """Test is_file_path method."""
    s3 = S3(S3Cfg(aws_access_key_id="test", aws_secret_access_key="test"))

    # Test with known file extension
    assert s3.is_file_path("s3://bucket/key/file.txt")
    assert s3.is_file_path("s3://bucket/key/file.csv")
    assert s3.is_file_path("s3://bucket/key/file.json")

    # Test with ambiguous path (requires S3 client)
    with patch.object(s3, "client") as mock_client:
        # Set up the exceptions attribute
        mock_client.exceptions.ClientError = ClientError
        mock_client.head_object.return_value = True
        assert s3.is_file_path("s3://bucket/key/file_without_extension")

        mock_client.head_object.side_effect = ClientError(
            {"Error": {"Code": "404"}}, "head_object"
        )
        assert not s3.is_file_path("s3://bucket/key/directory")


@mock_aws
def test_upload():
    """Test upload method with moto."""
    # Setup
    s3 = S3(S3Cfg(aws_access_key_id="test", aws_secret_access_key="test"))
    s3_client = boto3.client("s3", region_name="us-east-1")
    s3_client.create_bucket(Bucket="test-bucket")

    # Create a test file
    with open("test_file.txt", "w") as f:
        f.write("test content")

    # Test upload
    with patch.object(s3, "client", s3_client):
        s3.upload("test_file.txt", "test-bucket", partition_relative_to=None)

        # Verify file was uploaded
        response = s3_client.list_objects(Bucket="test-bucket")
        assert len(response["Contents"]) == 1
        assert response["Contents"][0]["Key"] == "test_file.txt"

    # Clean up
    import os

    os.remove("test_file.txt")


@mock_aws
def test_read_file():
    """Test read_file method with moto."""
    # Setup
    s3 = S3(S3Cfg(aws_access_key_id="test", aws_secret_access_key="test"))
    s3_client = boto3.client("s3", region_name="us-east-1")
    s3_client.create_bucket(Bucket="test-bucket")

    # Upload a test file
    s3_client.put_object(Bucket="test-bucket", Key="test_file.txt", Body="test content")

    # Test read_file
    with patch.object(s3, "client", s3_client):
        file_content = s3.read_file("s3://test-bucket/test_file.txt")
        assert file_content.read() == b"test content"


@mock_aws
def test_download_file(temp_dir):
    """Test download_file method with moto."""
    # Setup
    s3 = S3(S3Cfg(aws_access_key_id="test", aws_secret_access_key="test"))
    s3_client = boto3.client("s3", region_name="us-east-1")
    s3_client.create_bucket(Bucket="test-bucket")

    # Upload a test file
    s3_client.put_object(Bucket="test-bucket", Key="test_file.txt", Body="test content")

    # Test download_file to path with filename
    with patch.object(s3, "client", s3_client):
        local_file = temp_dir / "downloaded.txt"
        result = s3.download_file("s3://test-bucket/test_file.txt", local_file)
        assert result is True
        assert local_file.exists()
        assert local_file.read_text() == "test content"

    # Test download_file to directory
    with patch.object(s3, "client", s3_client):
        result = s3.download_file("s3://test-bucket/test_file.txt", temp_dir)
        assert result is True
        expected_path = temp_dir / "test-bucket" / "test_file.txt"
        assert expected_path.exists()
        assert expected_path.read_text() == "test content"

    # Test overwrite=False when file exists
    with patch.object(s3, "client", s3_client):
        result = s3.download_file(
            "s3://test-bucket/test_file.txt", local_file, overwrite=False
        )
        assert result is False


def test_delete_file():
    """Test delete_file method."""
    s3 = S3(S3Cfg(aws_access_key_id="test", aws_secret_access_key="test"))

    with patch.object(s3, "client") as mock_client:
        s3.delete_file("s3://test-bucket/test_file.txt")
        mock_client.delete_object.assert_called_once_with(
            Bucket="test-bucket", Key="test_file.txt"
        )

    # Test if_exists=True with 404 error
    with patch.object(s3, "client") as mock_client:
        mock_client.delete_object.side_effect = ClientError(
            {"Error": {"Code": "404"}}, "delete_object"
        )
        # Should not raise exception with if_exists=True
        s3.delete_file("s3://test-bucket/non_existent.txt", if_exists=True)

        # Should raise exception with if_exists=False
        with pytest.raises(ClientError):
            s3.delete_file("s3://test-bucket/non_existent.txt", if_exists=False)


def test_exists():
    """Test exists method."""
    s3 = S3(S3Cfg(aws_access_key_id="test", aws_secret_access_key="test"))

    # Test file exists
    with patch.object(s3, "client") as mock_client:
        mock_client.head_object.return_value = {}
        assert s3.exists("s3://test-bucket/test_file.txt") is True
        mock_client.head_object.assert_called_once_with(
            Bucket="test-bucket", Key="test_file.txt"
        )

    # Test file does not exist
    with patch.object(s3, "client") as mock_client:
        mock_client.head_object.side_effect = ClientError(
            {"Error": {"Code": "404"}}, "head_object"
        )
        assert s3.exists("s3://test-bucket/non_existent.txt") is False

    # Test bucket exists
    with patch.object(s3, "client") as mock_client:
        mock_client.head_bucket.return_value = {}
        assert s3.exists("s3://test-bucket") is True
        mock_client.head_bucket.assert_called_once_with(Bucket="test-bucket")

    # Test bucket does not exist
    with patch.object(s3, "client") as mock_client:
        mock_client.head_bucket.side_effect = ClientError(
            {"Error": {"Code": "404"}}, "head_bucket"
        )
        assert s3.exists("s3://non-existent-bucket") is False


def test_file_size():
    """Test file_size method."""
    s3 = S3(S3Cfg(aws_access_key_id="test", aws_secret_access_key="test"))

    with patch.object(s3, "resource") as mock_resource:
        mock_object = MagicMock()
        mock_object.content_length = 42
        mock_resource.Object.return_value = mock_object

        file_size = s3.file_size("s3://test-bucket/test_file.txt")
        assert file_size == 42
        mock_resource.Object.assert_called_once_with("test-bucket", "test_file.txt")


@mock_aws
def test_get_bucket():
    """Test get_bucket method."""
    # Setup
    s3 = S3(
        S3Cfg(
            aws_access_key_id="test",
            aws_secret_access_key="test",
            s3_region="us-east-1",
        )
    )

    # Bucket doesn't exist yet
    bucket = s3.get_bucket("new-test-bucket")
    assert bucket.name == "new-test-bucket"

    # Verify bucket was created
    response = s3.client.list_buckets()
    bucket_names = [b["Name"] for b in response["Buckets"]]
    assert "new-test-bucket" in bucket_names


def test_list_buckets():
    """Test list_buckets method."""
    s3 = S3(S3Cfg(aws_access_key_id="test", aws_secret_access_key="test"))

    with patch.object(s3, "client") as mock_client:
        mock_client.list_buckets.return_value = {
            "Buckets": [
                {"Name": "bucket1"},
                {"Name": "bucket2"},
                {"Name": "test-bucket"},
            ]
        }

        buckets = s3.list_buckets()
        assert buckets == ["bucket1", "bucket2", "test-bucket"]

        # Test with pattern
        buckets = s3.list_buckets(pattern="test*")
        assert buckets == ["test-bucket"]


@mock_aws
def test_list_files():
    """Test list_files method with moto."""
    # Setup
    s3 = S3(S3Cfg(aws_access_key_id="test", aws_secret_access_key="test"))
    s3_client = boto3.client("s3", region_name="us-east-1")
    s3_client.create_bucket(Bucket="test-bucket")

    # Create some test objects
    s3_client.put_object(Bucket="test-bucket", Key="file1.txt", Body="content")
    s3_client.put_object(Bucket="test-bucket", Key="folder/file2.txt", Body="content")
    s3_client.put_object(Bucket="test-bucket", Key="folder/file3.csv", Body="content")

    # Test with moto - patch the client
    with patch.object(s3, "client", s3_client):
        # List all files
        files = s3.list_files("s3://test-bucket/", return_as="paths")
        assert sorted(files) == [
            "file1.txt",
            "folder/file2.txt",
            "folder/file3.csv",
        ]

        # List files in partition
        files = s3.list_files("s3://test-bucket/folder/", return_as="paths")
        assert sorted(files) == ["folder/file2.txt", "folder/file3.csv"]

        # Test return_as='urls'
        files = s3.list_files("s3://test-bucket/folder/", return_as="urls")
        assert sorted(files) == [
            "s3://test-bucket/folder/file2.txt",
            "s3://test-bucket/folder/file3.csv",
        ]

        # Test return_as='names'
        files = s3.list_files("s3://test-bucket/folder/", return_as="names")
        assert sorted(files) == ["file2.txt", "file3.csv"]
