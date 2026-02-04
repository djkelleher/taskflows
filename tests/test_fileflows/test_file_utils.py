import gzip
import os
import shutil
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest
from taskflows.files.extensions import file_extensions_re
from taskflows.files.utils import (
    csv_to_parquet,
    csvs_to_parquet,
    gzip_file,
    gzip_files,
    with_parquet_extension,
)


def test_gzip_file(temp_dir):
    """Test gzip_file function."""
    # Create a test file
    test_file = temp_dir / "test.csv"
    with open(test_file, "w") as f:
        f.write("a,b,c\n1,2,3\n")

    # Test gzip_file with default suffix
    gzip_file(test_file)

    # Check that original file is deleted
    assert not test_file.exists()

    # Check that gzipped file exists
    gzipped_file = temp_dir / "test.csv.gz"
    assert gzipped_file.exists()

    # Check content of gzipped file
    with gzip.open(gzipped_file, "rt") as f:
        content = f.read()
        assert content == "a,b,c\n1,2,3\n"

    # Test gzip_file with custom suffix and delete=False
    test_file = temp_dir / "test2.csv"
    with open(test_file, "w") as f:
        f.write("a,b,c\n4,5,6\n")

    gzip_file(test_file, suffix=".custom.gz", delete=False)

    # Check that original file is not deleted
    assert test_file.exists()

    # Check that gzipped file exists with custom suffix
    gzipped_file = temp_dir / "test2.custom.gz"
    assert gzipped_file.exists()


def test_gzip_files(temp_dir):
    """Test gzip_files function."""
    # Create test files
    files = []
    for i in range(3):
        file_path = temp_dir / f"test{i}.csv"
        with open(file_path, "w") as f:
            f.write(f"a,b,c\n{i},{i+1},{i+2}\n")
        files.append(file_path)

    # Mock the Pool to avoid actual multiprocessing
    with patch("taskflows.files.utils.Pool") as mock_pool:
        mock_pool_instance = MagicMock()
        mock_pool.return_value.__enter__.return_value = mock_pool_instance

        # Test gzip_files
        gzip_files(files)

        # Check that map was called with the correct arguments
        mock_pool_instance.map.assert_called_once()

    # Real test with one process
    gzip_files(files, n_proc=1)

    # Check that original files are deleted
    for file_path in files:
        assert not file_path.exists()

    # Check that gzipped files exist
    for i in range(3):
        gzipped_file = temp_dir / f"test{i}.csv.gz"
        assert gzipped_file.exists()

        # Check content
        with gzip.open(gzipped_file, "rt") as f:
            content = f.read()
            assert content == f"a,b,c\n{i},{i+1},{i+2}\n"


def test_with_parquet_extension():
    """Test with_parquet_extension function."""
    # Test with simple filename
    path = Path("test.csv")
    result = with_parquet_extension(path)
    assert result == Path("test.parquet")

    # Test with multiple extensions
    path = Path("test.csv.gz")
    result = with_parquet_extension(path)
    assert result == Path("test.parquet")

    # Test with directory
    path = Path("dir/test.csv")
    result = with_parquet_extension(path)
    assert result == Path("dir/test.parquet")


def test_csv_to_parquet(temp_dir, sample_csv_file):
    """Test csv_to_parquet function."""
    with patch("taskflows.files.utils.duckdb") as mock_duckdb:
        # Test with default save_path_generator
        csv_to_parquet(sample_csv_file)

        expected_save_path = with_parquet_extension(sample_csv_file)
        stmt = f"COPY (SELECT * FROM '{sample_csv_file}') TO '{expected_save_path}' (FORMAT PARQUET);"
        mock_duckdb.execute.assert_called_once_with(stmt)

        mock_duckdb.reset_mock()

        # Test with custom save_path_generator
        def custom_save_path_generator(file_path):
            return file_path.with_name(f"{file_path.stem}_custom.parquet")

        csv_to_parquet(
            sample_csv_file, save_path_generator=custom_save_path_generator
        )

        expected_save_path = custom_save_path_generator(sample_csv_file)
        stmt = f"COPY (SELECT * FROM '{sample_csv_file}') TO '{expected_save_path}' (FORMAT PARQUET);"
        mock_duckdb.execute.assert_called_once_with(stmt)


def test_csvs_to_parquet(temp_dir):
    """Test csvs_to_parquet function."""
    # Create test CSV files
    csv_files = []
    for i in range(3):
        file_path = temp_dir / f"test{i}.csv.gz"
        with gzip.open(file_path, "wt") as f:
            f.write(f"a,b,c\n{i},{i+1},{i+2}\n")
        csv_files.append(file_path)

    with patch("taskflows.files.utils.csv_to_parquet") as mock_csv_to_parquet, patch(
        "taskflows.files.utils.os.remove"
    ) as mock_remove:
        # Test with single file
        csvs_to_parquet([csv_files[0]])
        mock_csv_to_parquet.assert_called_once()
        mock_remove.assert_called_once_with(csv_files[0])

        mock_csv_to_parquet.reset_mock()
        mock_remove.reset_mock()

        # Test with multiple files
        with patch("taskflows.files.utils.ProcessPoolExecutor") as mock_executor:
            mock_executor_instance = MagicMock()
            mock_executor.return_value.__enter__.return_value = mock_executor_instance
            mock_executor_instance.map.return_value = ["result1", "result2", "result3"]

            csvs_to_parquet(csv_files)

            mock_executor_instance.map.assert_called_once()
            assert mock_remove.call_count == 3

    # Test with directory input
    with patch("taskflows.files.utils.csv_to_parquet") as mock_csv_to_parquet, patch(
        "taskflows.files.utils.os.remove"
    ) as mock_remove, patch("pathlib.Path.glob", return_value=csv_files), patch(
        "taskflows.files.utils.ProcessPoolExecutor"
    ) as mock_executor:
        mock_executor_instance = MagicMock()
        mock_executor.return_value.__enter__.return_value = mock_executor_instance
        mock_executor_instance.map.return_value = ["result1", "result2", "result3"]

        csvs_to_parquet(temp_dir)
        # Should call csv_to_parquet via ProcessPoolExecutor
        mock_executor_instance.map.assert_called_once()


def test_file_extensions_re():
    """Test file_extensions_re regular expression."""
    # Test with known file extensions
    assert file_extensions_re.search("test.csv")
    assert file_extensions_re.search("test.txt")
    assert file_extensions_re.search("test.json")
    assert file_extensions_re.search("test.parquet")
    assert file_extensions_re.search("path/to/test.pdf")

    # Test with unknown extension
    assert not file_extensions_re.search("test.unknown")

    # Test with no extension
    assert not file_extensions_re.search("test")
    assert not file_extensions_re.search("test")
