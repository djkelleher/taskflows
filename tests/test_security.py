"""Security validation tests for taskflows.

Tests for path traversal prevention, service name validation,
and command injection prevention.
"""

import pytest
from pathlib import Path
from taskflows.security_validation import (
    validate_env_file_path,
    validate_service_name,
    validate_command,
)
from taskflows.exceptions import SecurityError, ValidationError


class TestPathTraversalPrevention:
    """Test validate_env_file_path blocks directory traversal attacks."""

    def test_valid_absolute_path(self, tmp_path):
        """Test that valid absolute paths are accepted."""
        env_file = tmp_path / "test.env"
        env_file.write_text("KEY=value")

        result = validate_env_file_path(env_file)
        assert result == env_file.resolve()

    def test_valid_relative_path_in_cwd(self, tmp_path, monkeypatch):
        """Test that relative paths within cwd are accepted."""
        monkeypatch.chdir(tmp_path)
        env_file = Path("test.env")
        (tmp_path / "test.env").write_text("KEY=value")

        result = validate_env_file_path(env_file)
        assert result == (tmp_path / "test.env").resolve()

    def test_parent_directory_traversal_blocked(self, tmp_path):
        """Test that ../ traversal is blocked."""
        with pytest.raises(SecurityError):
            validate_env_file_path(tmp_path / "../../../etc/passwd")

    def test_dot_dot_in_path_blocked(self, tmp_path):
        """Test that paths containing .. are blocked."""
        with pytest.raises(SecurityError):
            validate_env_file_path(tmp_path / "foo/../../../etc/passwd")

    def test_symlink_escape_blocked(self, tmp_path):
        """Test that symlinks pointing outside allowed dirs are blocked."""
        # Create a symlink pointing to /etc/passwd
        link = tmp_path / "link.env"
        link.symlink_to("/etc/passwd")

        # Should be blocked when symlink points outside allowed directories
        with pytest.raises(SecurityError):
            validate_env_file_path(link)

    def test_allow_nonexistent_file(self, tmp_path):
        """Test that nonexistent files can be allowed."""
        nonexistent = tmp_path / "nonexistent.env"

        # Should raise by default
        with pytest.raises(SecurityError, match="No such file"):
            validate_env_file_path(nonexistent, allow_nonexistent=False)

        # Should succeed when allowed
        result = validate_env_file_path(nonexistent, allow_nonexistent=True)
        assert result == nonexistent.resolve()

    def test_home_directory_expansion(self, tmp_path, monkeypatch):
        """Test that ~ is properly expanded and validated."""
        # Create a test file in home
        home_dir = tmp_path / "home"
        home_dir.mkdir()
        env_file = home_dir / "test.env"
        env_file.write_text("KEY=value")

        # Mock home directory
        monkeypatch.setenv("HOME", str(home_dir))

        result = validate_env_file_path("~/test.env")
        assert result == env_file.resolve()


class TestServiceNameValidation:
    """Test validate_service_name sanitizes service names."""

    def test_valid_simple_name(self):
        """Test that simple alphanumeric names are accepted."""
        assert validate_service_name("myservice") == "myservice"

    def test_valid_name_with_dash(self):
        """Test that names with dashes are accepted."""
        assert validate_service_name("my-service") == "my-service"

    def test_valid_name_with_underscore(self):
        """Test that names with underscores are accepted."""
        assert validate_service_name("my_service") == "my_service"

    def test_valid_name_with_dot(self):
        """Test that names with dots are accepted."""
        assert validate_service_name("my.service") == "my.service"

    def test_valid_name_with_numbers(self):
        """Test that names with numbers are accepted."""
        assert validate_service_name("service123") == "service123"

    def test_mixed_valid_characters(self):
        """Test complex but valid service name."""
        assert validate_service_name("my-service_2.0") == "my-service_2.0"

    def test_reject_path_traversal(self):
        """Test that .. is rejected."""
        with pytest.raises(ValidationError, match="Invalid service name"):
            validate_service_name("../etc/passwd")

    def test_reject_absolute_path(self):
        """Test that absolute paths are rejected."""
        with pytest.raises(ValidationError, match="Invalid service name"):
            validate_service_name("/etc/passwd")

    def test_reject_forward_slash(self):
        """Test that / is rejected."""
        with pytest.raises(ValidationError, match="Invalid service name"):
            validate_service_name("my/service")

    def test_reject_special_characters(self):
        """Test that special characters are rejected."""
        invalid_names = [
            "my service",  # space
            "my@service",  # @
            "my#service",  # #
            "my$service",  # $
            "my&service",  # &
            "my*service",  # *
            "my(service",  # (
            "my)service",  # )
        ]
        for name in invalid_names:
            with pytest.raises(ValidationError, match="Invalid service name"):
                validate_service_name(name)

    def test_reject_empty_name(self):
        """Test that empty names are rejected."""
        with pytest.raises(ValidationError, match="Invalid service name"):
            validate_service_name("")

    def test_reject_whitespace_only(self):
        """Test that whitespace-only names are rejected."""
        with pytest.raises(ValidationError, match="Invalid service name"):
            validate_service_name("   ")


class TestCommandInjectionPrevention:
    """Test validate_command prevents injection attacks."""

    def test_valid_simple_command(self):
        """Test that simple commands are accepted."""
        cmd = "python script.py"
        result = validate_command(cmd)
        assert result == cmd

    def test_valid_command_with_args(self):
        """Test that commands with arguments are accepted."""
        cmd = "python script.py --arg1 value1 --arg2 value2"
        result = validate_command(cmd)
        assert result == cmd

    def test_valid_quoted_args(self):
        """Test that quoted arguments are properly parsed."""
        cmd = 'python script.py --message "hello world"'
        result = validate_command(cmd)
        assert result == cmd

    def test_valid_single_quoted_args(self):
        """Test that single-quoted arguments are properly parsed."""
        cmd = "python script.py --message 'hello world'"
        result = validate_command(cmd)
        assert result == cmd

    def test_reject_null_bytes(self):
        """Test that null bytes are rejected."""
        cmd = "python script.py\x00malicious"
        with pytest.raises(ValidationError, match="null bytes"):
            validate_command(cmd)

    def test_dangerous_patterns_logged(self):
        """Test that dangerous patterns are logged but allowed."""
        cmd = "python script.py --arg 'value; rm -rf /'"
        result = validate_command(cmd)
        # Should return the command (with warning logged)
        assert result == cmd

    def test_escaped_characters(self):
        """Test that escaped characters are handled correctly."""
        cmd = r"python script.py --path /home/user/file\ with\ spaces.txt"
        result = validate_command(cmd)
        assert result == cmd


class TestDockerContainerEnvFileValidation:
    """Integration tests for DockerContainer env_file validation."""

    def test_docker_container_validates_env_file(self, tmp_path):
        """Test that DockerContainer validates env_file on creation."""
        from taskflows.docker import DockerContainer

        # Create a valid env file
        env_file = tmp_path / "valid.env"
        env_file.write_text("KEY=value")

        # Should succeed with valid path
        container = DockerContainer(
            name="test",
            image="python:3.12",
            env_file=str(env_file),
        )
        assert Path(container.env_file) == env_file.resolve()

    def test_docker_container_blocks_traversal(self, tmp_path):
        """Test that DockerContainer blocks path traversal in env_file."""
        from taskflows.docker import DockerContainer
        from taskflows.exceptions import SecurityError, ValidationError

        # Should raise SecurityError for path traversal
        # Need enough ../ to escape /tmp (pytest tmp_path is deeply nested)
        with pytest.raises(SecurityError):
            DockerContainer(
                name="test",
                image="python:3.12",
                env_file=str(tmp_path / "../../../../../../etc/passwd"),
            )


class TestServiceEnvFileValidation:
    """Integration tests for Service env_file validation."""

    def test_service_validates_env_file(self, tmp_path):
        """Test that Service validates env_file on creation."""
        from taskflows.service import Service

        # Create a valid env file
        env_file = tmp_path / "valid.env"
        env_file.write_text("KEY=value")

        # Should succeed with valid path
        service = Service(
            name="test-service",
            start_command="python script.py",
            env_file=str(env_file),
        )
        assert Path(service.env_file) == env_file.resolve()

    def test_service_blocks_traversal(self, tmp_path):
        """Test that Service blocks path traversal in env_file."""
        from taskflows.service import Service
        from taskflows.exceptions import SecurityError, ValidationError

        # Should raise SecurityError for path traversal
        # Need enough ../ to escape /tmp (pytest tmp_path is deeply nested)
        with pytest.raises(SecurityError):
            Service(
                name="test-service",
                start_command="python script.py",
                env_file=str(tmp_path / "../../../../../../etc/passwd"),
            )

    def test_service_validates_name(self):
        """Test that Service validates service name."""
        from taskflows.service import Service
        from taskflows.exceptions import SecurityError, ValidationError

        # Should raise ValidationError for invalid name
        with pytest.raises(ValidationError):
            Service(
                name="../malicious",
                start_command="python script.py",
            )
