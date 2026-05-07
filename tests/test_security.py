"""Security validation tests for taskflows.

Tests for path traversal prevention, service name validation,
and command injection prevention.
"""

import pytest
from pathlib import Path
from taskflows.admin import auth as admin_auth
from taskflows.admin import security as admin_security
from taskflows.security_validation import (
    validate_command,
    validate_env_file_path,
    validate_service_name,
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

    @pytest.mark.parametrize("name", [".", "-", ".hidden", "-unit", "unit.", "unit-"])
    def test_reject_ambiguous_punctuation_boundaries(self, name):
        """Service names should not create hidden or punctuation-only unit names."""
        with pytest.raises(ValidationError, match="Invalid service name"):
            validate_service_name(name)


class TestCommandValidation:
    """Test validate_command gives predictable errors."""

    @pytest.mark.parametrize("command", [None, "", "   ", ["echo", "hello"]])
    def test_reject_invalid_command_values(self, command):
        with pytest.raises(ValidationError):
            validate_command(command)

    def test_reject_null_bytes(self):
        with pytest.raises(SecurityError):
            validate_command("echo ok\x00")

    def test_allow_plain_command(self):
        assert validate_command("python script.py") == "python script.py"


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

        # Should raise ValidationError for invalid name
        with pytest.raises(ValidationError):
            Service(
                name="../malicious",
                start_command="python script.py",
            )


class TestSystemdUnitValidation:
    """Integration tests for systemd unit directive hardening."""

    def test_service_blocks_description_newline_injection(self):
        from taskflows.service import Service

        with pytest.raises(SecurityError):
            Service(
                name="test-service",
                start_command="python script.py",
                description="safe\n[Service]\nExecStart=/bin/evil",
            )

    def test_service_blocks_environment_value_newline_injection(self):
        from taskflows.service import Service

        with pytest.raises(SecurityError):
            Service(
                name="test-service",
                start_command="python script.py",
                env={"SAFE": "ok\nEnvironment=EVIL=1"},
            )

    def test_service_blocks_invalid_environment_key(self):
        from taskflows.service import Service

        with pytest.raises(ValidationError):
            Service(
                name="test-service",
                start_command="python script.py",
                env={"BAD-NAME": "value"},
            )


class TestAdminSecurityState:
    def test_malformed_password_hash_fails_closed(self):
        assert admin_auth.verify_password("password", "not-a-valid-hash") is False

    def test_corrupt_users_file_fails_closed(self, tmp_path, monkeypatch):
        users_file = tmp_path / "users.json"
        users_file.write_text("{not-json")
        monkeypatch.setattr(admin_auth, "users_file", users_file)

        with pytest.raises(RuntimeError, match="not valid JSON"):
            admin_auth.load_users()

    def test_non_object_ui_config_fails_closed(self, tmp_path, monkeypatch):
        ui_config_file = tmp_path / "ui_config.json"
        ui_config_file.write_text("[]")
        monkeypatch.setattr(admin_auth, "ui_config_file", ui_config_file)
        monkeypatch.delenv(admin_auth.ENV_JWT_SECRET, raising=False)

        with pytest.raises(RuntimeError, match="must contain a JSON object"):
            admin_auth.load_ui_config()

    def test_refresh_token_revocation_blocks_reuse(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            admin_auth, "refresh_tokens_file", tmp_path / "refresh_tokens.json"
        )

        token = admin_auth.create_refresh_token("alice", "jwt-secret")

        assert admin_auth.verify_token(token, "jwt-secret", "refresh") == "alice"
        assert admin_auth.revoke_refresh_token(token, "jwt-secret") is True
        assert admin_auth.verify_token(token, "jwt-secret", "refresh") is None

    def test_csrf_tokens_are_session_scoped(self, tmp_path, monkeypatch):
        monkeypatch.setattr(admin_security, "_csrf_tokens_file", tmp_path / "csrf.json")

        token_one = {
            "token": "token-one",
            "expiry": 4_000_000_000,
            "signature": "sig-one",
            "username": "alice",
        }
        token_two = {
            "token": "token-two",
            "expiry": 4_000_000_000,
            "signature": "sig-two",
            "username": "alice",
        }

        admin_security.store_csrf_token("alice", token_one)
        admin_security.store_csrf_token("alice", token_two)

        assert admin_security.get_csrf_token_data("alice", "token-one") == token_one
        assert admin_security.get_csrf_token_data("alice", "token-two") == token_two

        admin_security.remove_csrf_token("alice", "token-one")

        assert admin_security.get_csrf_token_data("alice", "token-one") is None
        assert admin_security.get_csrf_token_data("alice", "token-two") == token_two

    def test_corrupt_security_state_fails_closed(self, tmp_path, monkeypatch):
        csrf_file = tmp_path / "csrf.json"
        csrf_file.write_text("{not-json")
        monkeypatch.setattr(admin_security, "_csrf_tokens_file", csrf_file)

        with pytest.raises(RuntimeError, match="corrupt"):
            admin_security.get_csrf_token_data("alice", "token")

    def test_hmac_signature_requires_request_binding(self):
        with pytest.raises(ValueError, match="method, path, and nonce"):
            admin_security.calculate_hmac_signature("secret", "123", "")

    def test_malformed_csrf_token_fails_closed(self):
        valid, error = admin_security.validate_csrf_token(
            "token",
            "alice",
            "not-an-int",
            "signature",
            "secret",
        )

        assert valid is False
        assert error == "Invalid CSRF token expiry"
