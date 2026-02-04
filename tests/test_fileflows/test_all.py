import pytest


def test_imports():
    """Test that all modules can be imported."""
    from taskflows.files import S3, Files, S3Cfg
    from taskflows.files.core import Files
    from taskflows.files.extensions import file_extensions_re
    from taskflows.files.s3 import S3, S3Cfg
    from taskflows.files.utils import (
        csv_to_parquet,
        csvs_to_parquet,
        gzip_file,
        gzip_files,
        with_parquet_extension,
    )


def test_package_structure():
    """Test that the package structure is as expected."""
    import taskflows.files as files

    # Check top-level exports
    assert hasattr(files, "Files")
    assert hasattr(files, "S3")
    assert hasattr(files, "S3Cfg")
    assert hasattr(files, "create_duckdb_secret")
    assert hasattr(files, "is_s3_path")

    # Check utils are imported
    assert hasattr(files, "gzip_file")
    assert hasattr(files, "gzip_files")
    assert hasattr(files, "with_parquet_extension")
    assert hasattr(files, "csvs_to_parquet")
    assert hasattr(files, "csv_to_parquet")


@pytest.mark.parametrize(
    "path,expected",
    [
        ("s3://bucket/key", True),
        ("s3://bucket", True),
        ("file:///path/to/file", False),
        ("/local/path", False),
        ("relative/path", False),
    ],
)
def test_is_s3_path(path, expected):
    """Test is_s3_path function with various paths."""
    from taskflows.files.s3 import is_s3_path

    assert is_s3_path(path) == expected
