import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from files import Files
from files.s3 import S3


@pytest.fixture
def files_instance(s3_cfg):
    """Create a Files instance with mocked S3 client."""
    with patch.object(S3, "_boto3_obj", return_value=MagicMock()):
        files = Files(s3_cfg)
        yield files


def test_create_local_directory(files_instance, temp_dir):
    """Test creating a local directory."""
    test_dir = temp_dir / "test_dir"
    files_instance.mkdir(test_dir)
    assert test_dir.exists()


def test_create_s3_bucket(files_instance):
    """Test creating an S3 bucket."""
    with patch.object(files_instance.s3, "get_bucket") as mock_get_bucket:
        files_instance.mkdir("s3://test-bucket")
        mock_get_bucket.assert_called_once_with("test-bucket")


def test_copy_local_to_local(files_instance, sample_file, temp_dir):
    """Test copying a local file to another local path."""
    destination = temp_dir / "destination.txt"
    files_instance.copy(sample_file, destination)
    assert destination.exists()
    with open(destination, "r") as f:
        assert f.read() == "This is a test file."


def test_move_local_to_local(files_instance, sample_file, temp_dir):
    """Test moving a local file to another local path."""
    destination = temp_dir / "destination.txt"
    files_instance.move(sample_file, destination)
    assert destination.exists()
    assert not sample_file.exists()
    with open(destination, "r") as f:
        assert f.read() == "This is a test file."


def test_move_local_to_local_with_verify(files_instance, sample_file, temp_dir):
    """Test moving a local file with verification."""
    destination = temp_dir / "destination.txt"
    files_instance.move(sample_file, destination)
    assert destination.exists()
    assert not sample_file.exists()


def test_move_with_verify_fails_if_destination_missing(files_instance, sample_file, temp_dir):
    """Test that move with verify raises error if destination doesn't exist."""
    destination = temp_dir / "destination.txt"
    with patch.object(files_instance, "exists", return_value=False):
        with pytest.raises(FileNotFoundError, match="does not exist after transfer"):
            files_instance.move(sample_file, destination)


def test_copy_local_to_s3(files_instance, sample_file):
    """Test copying a local file to S3."""
    with patch.object(files_instance.s3.client, "upload_file") as mock_upload_file:
        files_instance.copy(sample_file, "s3://test-bucket/sample.txt")
        mock_upload_file.assert_called_once_with(
            str(sample_file), "test-bucket", "sample.txt"
        )


def test_copy_s3_to_local(files_instance, temp_dir):
    """Test copying an S3 file to local."""
    destination = temp_dir / "destination.txt"
    with patch.object(files_instance.s3, "download_file") as mock_download_file:
        files_instance.copy("s3://test-bucket/sample.txt", destination)
        mock_download_file.assert_called_once()


def test_copy_s3_to_s3(files_instance):
    """Test copying an S3 file to another S3 location."""
    with patch.object(files_instance.s3, "move") as mock_move:
        files_instance.copy(
            "s3://test-bucket/sample.txt", "s3://test-bucket2/sample.txt"
        )
        mock_move.assert_called_once_with(
            src_path="s3://test-bucket/sample.txt",
            dst_path="s3://test-bucket2/sample.txt",
            delete_src=False,
        )


def test_delete_local_file(files_instance, sample_file):
    """Test deleting a local file."""
    files_instance.delete(sample_file)
    assert not sample_file.exists()


def test_delete_s3_file(files_instance):
    """Test deleting an S3 file."""
    with patch.object(files_instance.s3, "delete_file") as mock_delete_file:
        files_instance.delete("s3://test-bucket/sample.txt")
        mock_delete_file.assert_called_once_with(
            "s3://test-bucket/sample.txt", if_exists=False
        )


def test_exists_local_file(files_instance, sample_file, temp_dir):
    """Test checking if a local file exists."""
    assert files_instance.exists(sample_file)
    assert not files_instance.exists(temp_dir / "non_existent.txt")


def test_exists_s3_file(files_instance):
    """Test checking if an S3 file exists."""
    with patch.object(files_instance.s3, "exists", return_value=True) as mock_exists:
        assert files_instance.exists("s3://test-bucket/sample.txt")
        mock_exists.assert_called_once_with("s3://test-bucket/sample.txt")


def test_file_size_local(files_instance, sample_file):
    """Test getting the size of a local file."""
    assert files_instance.file_size(sample_file) == len("This is a test file.")


def test_file_size_s3(files_instance):
    """Test getting the size of an S3 file."""
    with patch.object(
        files_instance.s3, "file_size", return_value=20
    ) as mock_file_size:
        assert files_instance.file_size("s3://test-bucket/sample.txt") == 20
        mock_file_size.assert_called_once_with("s3://test-bucket/sample.txt")


def test_list_files_local(files_instance, temp_dir):
    """Test listing files in a local directory."""
    # Create some test files
    (temp_dir / "file1.txt").touch()
    (temp_dir / "file2.txt").touch()
    (temp_dir / "file3.csv").touch()

    # List all files
    files = files_instance.list_files(temp_dir)
    assert len(files) == 3
    assert set(f.name for f in files) == {"file1.txt", "file2.txt", "file3.csv"}

    # List with pattern
    files = files_instance.list_files(temp_dir, "*.txt")
    assert len(files) == 2
    assert set(f.name for f in files) == {"file1.txt", "file2.txt"}


def test_list_files_s3(files_instance):
    """Test listing files in an S3 directory."""
    with patch.object(
        files_instance.s3,
        "list_files",
        return_value=["s3://test-bucket/file1.txt", "s3://test-bucket/file2.txt"],
    ) as mock_list_files:
        files = files_instance.list_files("s3://test-bucket")
        assert len(files) == 2
        assert "s3://test-bucket/file1.txt" in files
        mock_list_files.assert_called_once()


def test_parquet_column_names(files_instance, sample_parquet_file):
    """Test getting column names from a parquet file."""
    column_names = files_instance.parquet_column_names(sample_parquet_file)
    assert column_names == ["A", "B"]


def test_parquet_column_names_s3(files_instance):
    """Test getting column names from an S3 parquet file."""
    with patch("pyarrow.parquet.read_schema", return_value=MagicMock(names=["A", "B"])):
        with patch.object(files_instance.s3, "arrow_fs", return_value=MagicMock()):
            column_names = files_instance.parquet_column_names(
                "s3://test-bucket/sample.parquet"
            )
            assert column_names == ["A", "B"]
