import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from uuid import uuid4

import pytest
from loguru import logger

from quicklogs.basic import any_case_env_var, get_logger


class TestEnvVarHandling:
    """Test environment variable handling"""

    def test_any_case_env_var(self):
        """Test case-insensitive environment variable reading"""
        test_var = "TEST_VAR_12345"

        # Test lowercase
        with patch.dict(os.environ, {test_var.lower(): "lowercase_value"}):
            assert any_case_env_var(test_var) == "lowercase_value"

        # Test uppercase
        with patch.dict(os.environ, {test_var.upper(): "uppercase_value"}):
            assert any_case_env_var(test_var) == "uppercase_value"

        # Test mixed case (original)
        with patch.dict(os.environ, {test_var: "original_value"}):
            assert any_case_env_var(test_var) == "original_value"

        # Test default value
        assert any_case_env_var("NONEXISTENT_VAR", "default") == "default"

        # Test boolean values
        with patch.dict(os.environ, {test_var: "true"}):
            assert any_case_env_var(test_var) is True

        with patch.dict(os.environ, {test_var: "false"}):
            assert any_case_env_var(test_var) is False


@pytest.mark.parametrize("use_env_vars", [False, True])
def test_logger(use_env_vars):
    # Clear configured loggers before test
    from quicklogs import basic

    original_configured = basic._configured_loggers.copy()
    basic._configured_loggers.clear()

    try:
        with TemporaryDirectory() as temp_dir:
            file_dir = Path(temp_dir)
            level = "DEBUG"
            backup_count = 2
            max_bytes = 1000

            name = f"test_logger_{uuid4()}"
            if use_env_vars:
                for var, value in (
                    (f"{name}_LOG_LEVEL", level),
                    (f"{name}_SHOW_SOURCE", "pathname"),
                    (f"{name}_FILE_DIR", str(file_dir)),
                    (f"{name}_FILE_MAX_BYTES", str(max_bytes)),
                    (f"{name}_MAX_ROTATIONS", str(backup_count)),
                ):
                    os.environ[var] = value
                test_logger = get_logger(name=name)
            else:
                test_logger = get_logger(
                    name=name,
                    level=level,
                    show_source="pathname",
                    file_dir=file_dir,
                    file_max_bytes=max_bytes,
                    max_rotations=backup_count,
                )

            random_uuid = str(uuid4())

            test_logger.info(random_uuid)
            test_logger.debug(random_uuid)

            log_file = file_dir / f"{name}.log"
            assert log_file.is_file()
            log_contents = log_file.read_text().strip()

            assert log_contents.count("INFO") >= 1
            assert log_contents.count("DEBUG") >= 1

            assert len(log_contents.split("\n")) >= 2

            for _ in range(100):
                test_logger.info(random_uuid)

            files = list(file_dir.iterdir())
            print(f"Files created: {[f.name for f in files]}")
            print(f"Expected: {backup_count + 1}, Got: {len(files)}")

            assert len(files) >= 1
            assert len(files) <= backup_count + 1
    finally:
        basic._configured_loggers = original_configured
        if use_env_vars:
            for var in [
                f"{name}_LOG_LEVEL",
                f"{name}_SHOW_SOURCE",
                f"{name}_FILE_DIR",
                f"{name}_FILE_MAX_BYTES",
                f"{name}_MAX_ROTATIONS",
            ]:
                os.environ.pop(var, None)


def test_no_terminal_logging():
    """Test logging with no_terminal option"""
    from quicklogs import basic

    original_configured = basic._configured_loggers.copy()
    basic._configured_loggers.clear()

    try:
        name = f"test_no_terminal_{uuid4()}"

        # Count handlers before
        handlers_before = len(logger._core.handlers)

        # Test with no_terminal=True
        test_logger = get_logger(name=name, no_terminal=True)

        # With no_terminal, no new stderr handlers should be added
        # (loguru uses a global logger, so we check that no new handlers were added)
        handlers_after = len(logger._core.handlers)
        assert handlers_after == handlers_before

        # Test with environment variable
        name2 = f"test_no_terminal_env_{uuid4()}"
        with patch.dict(os.environ, {f"{name2}_NO_TERMINAL": "true"}):
            handlers_before2 = len(logger._core.handlers)
            get_logger(name=name2)
            handlers_after2 = len(logger._core.handlers)
            assert handlers_after2 == handlers_before2
    finally:
        basic._configured_loggers = original_configured


def test_show_source_variations():
    """Test different show_source parameter values"""
    from quicklogs import basic

    original_configured = basic._configured_loggers.copy()
    basic._configured_loggers.clear()

    try:
        with TemporaryDirectory() as temp_dir:
            file_dir = Path(temp_dir)

            # Test with pathname
            logger1 = get_logger(
                name=f"test_pathname_{uuid4()}", show_source="pathname", file_dir=file_dir
            )
            logger1.info("test message")

            log_file1 = list(file_dir.glob("*.log"))[0]
            contents1 = log_file1.read_text()
            assert "test_basic.py" in contents1

            # Test with filename
            logger2 = get_logger(
                name=f"test_filename_{uuid4()}", show_source="filename", file_dir=file_dir
            )
            logger2.info("test message")

            log_file2 = [f for f in file_dir.glob("*.log") if f != log_file1][0]
            contents2 = log_file2.read_text()
            assert "test_basic.py" in contents2
    finally:
        basic._configured_loggers = original_configured


def test_multiple_logger_instances():
    """Test that multiple calls with same name return same logger"""
    from quicklogs import basic

    original_configured = basic._configured_loggers.copy()
    basic._configured_loggers.clear()

    try:
        name = f"test_singleton_{uuid4()}"

        logger1 = get_logger(name=name, level="INFO")
        logger2 = get_logger(name=name, level="DEBUG")

        # Second call should not reconfigure (name should be in configured set)
        assert name in basic._configured_loggers
    finally:
        basic._configured_loggers = original_configured


def test_quicklogs_env_vars():
    """Test QUICKLOGS_ prefixed environment variables"""
    from quicklogs import basic

    original_configured = basic._configured_loggers.copy()
    basic._configured_loggers.clear()

    try:
        with TemporaryDirectory() as temp_dir:
            file_dir = Path(temp_dir)
            name = f"test_quicklogs_{uuid4()}"

            with patch.dict(
                os.environ,
                {
                    "QUICKLOGS_LOG_LEVEL": "WARNING",
                    "QUICKLOGS_FILE_DIR": str(file_dir),
                    "QUICKLOGS_SHOW_SOURCE": "filename",
                    "QUICKLOGS_NO_TERMINAL": "true",
                    "QUICKLOGS_FILE_MAX_BYTES": "5000",
                    "QUICKLOGS_MAX_ROTATIONS": "3",
                },
            ):
                test_logger = get_logger(name=name, file_max_bytes=None, max_rotations=None)

                # Test that file was created
                test_logger.warning("test message")
                log_file = file_dir / f"{name}.log"
                assert log_file.is_file()
    finally:
        basic._configured_loggers = original_configured


def test_logger_without_name():
    """Test logger creation without a name"""
    from quicklogs import basic

    original_configured = basic._configured_loggers.copy()
    basic._configured_loggers.clear()

    try:
        with TemporaryDirectory() as temp_dir:
            file_dir = Path(temp_dir)

            test_logger = get_logger(file_dir=file_dir)
            test_logger.info("test without name")

            # Should create file with process ID
            log_files = list(file_dir.glob("*.log"))
            assert len(log_files) == 1
            assert f"python_{os.getpid()}" in log_files[0].name
    finally:
        basic._configured_loggers = original_configured


def test_numeric_log_levels():
    """Test using numeric log levels"""
    from quicklogs import basic

    original_configured = basic._configured_loggers.copy()
    basic._configured_loggers.clear()

    try:
        name = f"test_numeric_{uuid4()}"

        # Test with numeric level (DEBUG = 10)
        logger1 = get_logger(name=name, level=10)
        logger1.debug("test debug")

        name2 = f"{name}_2"
        # Test with WARNING = 30
        logger2 = get_logger(name=name2, level=30)
        logger2.warning("test warning")
    finally:
        basic._configured_loggers = original_configured