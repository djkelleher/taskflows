"""Tests for the tf discover CLI command."""

import pytest
from click.testing import CliRunner
from pathlib import Path

from taskflows.admin.cli import discover


@pytest.fixture
def temp_yaml_dir(tmp_path):
    """Create a temporary directory with test YAML files."""
    # Create directory structure
    configs_dir = tmp_path / "configs"
    configs_dir.mkdir()
    production_dir = configs_dir / "production"
    production_dir.mkdir()
    staging_dir = configs_dir / "staging"
    staging_dir.mkdir()

    # Create a file with taskflows_services (list format)
    services_yaml = production_dir / "services.yaml"
    services_yaml.write_text("""
taskflows_services:
  - name: web-server
    start_command: python server.py
  - name: worker
    start_command: python worker.py
  - name: scheduler
    start_command: python scheduler.py
""")

    # Create a file with taskflows_services (dict format)
    web_services_yml = staging_dir / "web-services.yml"
    web_services_yml.write_text("""
taskflows_services:
  api:
    start_command: python api.py
  frontend:
    start_command: npm start
""")

    # Create a file without taskflows_services
    other_yaml = configs_dir / "database.yaml"
    other_yaml.write_text("""
database:
  host: localhost
  port: 5432
""")

    # Create an empty file
    empty_yaml = configs_dir / "empty.yaml"
    empty_yaml.write_text("")

    # Create a file with non-dict content
    list_yaml = configs_dir / "list.yaml"
    list_yaml.write_text("""
- item1
- item2
""")

    # Create an invalid YAML file
    invalid_yaml = configs_dir / "invalid.yaml"
    invalid_yaml.write_text("""
invalid: yaml: content: [
""")

    return tmp_path


class TestDiscoverCommand:
    """Tests for the discover command."""

    def test_discover_finds_files_with_taskflows_services(self, temp_yaml_dir):
        """Test that discover finds files containing taskflows_services."""
        runner = CliRunner()
        result = runner.invoke(discover, [str(temp_yaml_dir / "configs")])

        assert result.exit_code == 0
        assert "services.yaml" in result.output
        assert "web-services.yml" in result.output
        assert "Found 2 file(s)" in result.output

    def test_discover_ignores_files_without_taskflows_services(self, temp_yaml_dir):
        """Test that discover ignores files without taskflows_services key."""
        runner = CliRunner()
        result = runner.invoke(discover, [str(temp_yaml_dir / "configs")])

        assert result.exit_code == 0
        assert "database.yaml" not in result.output
        assert "empty.yaml" not in result.output
        assert "list.yaml" not in result.output

    def test_discover_count_flag_shows_service_counts(self, temp_yaml_dir):
        """Test that --count flag shows number of services per file."""
        runner = CliRunner()
        result = runner.invoke(discover, ["--count", str(temp_yaml_dir / "configs")])

        assert result.exit_code == 0
        assert "(3 services)" in result.output  # production/services.yaml has 3 services
        assert "(2 services)" in result.output  # staging/web-services.yml has 2 services

    def test_discover_count_flag_short_form(self, temp_yaml_dir):
        """Test that -c flag works the same as --count."""
        runner = CliRunner()
        result = runner.invoke(discover, ["-c", str(temp_yaml_dir / "configs")])

        assert result.exit_code == 0
        assert "(3 services)" in result.output
        assert "(2 services)" in result.output

    def test_discover_verbose_shows_parse_warnings(self, temp_yaml_dir):
        """Test that --verbose flag shows parse warnings for invalid files."""
        runner = CliRunner()
        result = runner.invoke(discover, ["--verbose", str(temp_yaml_dir / "configs")])

        assert result.exit_code == 0
        assert "Warning:" in result.output
        assert "invalid.yaml" in result.output

    def test_discover_verbose_flag_short_form(self, temp_yaml_dir):
        """Test that -v flag works the same as --verbose."""
        runner = CliRunner()
        result = runner.invoke(discover, ["-v", str(temp_yaml_dir / "configs")])

        assert result.exit_code == 0
        assert "Warning:" in result.output

    def test_discover_without_verbose_hides_warnings(self, temp_yaml_dir):
        """Test that without --verbose, parse warnings are hidden."""
        runner = CliRunner()
        result = runner.invoke(discover, [str(temp_yaml_dir / "configs")])

        assert result.exit_code == 0
        assert "Warning:" not in result.output

    def test_discover_defaults_to_current_directory(self, temp_yaml_dir, monkeypatch):
        """Test that discover defaults to current directory when no path given."""
        monkeypatch.chdir(temp_yaml_dir / "configs")
        runner = CliRunner()
        result = runner.invoke(discover, [])

        assert result.exit_code == 0
        assert "Found 2 file(s)" in result.output

    def test_discover_nonexistent_path_fails(self):
        """Test that discover fails gracefully for nonexistent paths."""
        runner = CliRunner()
        result = runner.invoke(discover, ["/nonexistent/path"])

        assert result.exit_code != 0

    def test_discover_empty_directory(self, tmp_path):
        """Test discover on a directory with no YAML files."""
        runner = CliRunner()
        result = runner.invoke(discover, [str(tmp_path)])

        assert result.exit_code == 0
        assert "Found 0 file(s)" in result.output

    def test_discover_recursive_search(self, temp_yaml_dir):
        """Test that discover recursively searches subdirectories."""
        runner = CliRunner()
        result = runner.invoke(discover, [str(temp_yaml_dir)])

        assert result.exit_code == 0
        # Should find files in configs/production and configs/staging
        assert "production" in result.output
        assert "staging" in result.output

    def test_discover_combined_flags(self, temp_yaml_dir):
        """Test using both --count and --verbose flags together."""
        runner = CliRunner()
        result = runner.invoke(discover, ["-c", "-v", str(temp_yaml_dir / "configs")])

        assert result.exit_code == 0
        assert "(3 services)" in result.output
        assert "(2 services)" in result.output
        assert "Warning:" in result.output

    def test_discover_handles_empty_taskflows_services(self, tmp_path):
        """Test handling of files with empty taskflows_services."""
        yaml_file = tmp_path / "empty_services.yaml"
        yaml_file.write_text("""
taskflows_services:
""")
        runner = CliRunner()
        result = runner.invoke(discover, ["-c", str(tmp_path)])

        assert result.exit_code == 0
        assert "empty_services.yaml" in result.output
        assert "(0 services)" in result.output

    def test_discover_output_is_sorted(self, temp_yaml_dir):
        """Test that output files are sorted alphabetically."""
        runner = CliRunner()
        result = runner.invoke(discover, [str(temp_yaml_dir / "configs")])

        assert result.exit_code == 0
        lines = [line for line in result.output.split('\n') if line and not line.startswith('Found')]
        # Check that production comes before staging (alphabetically)
        production_idx = next((i for i, line in enumerate(lines) if 'production' in line), -1)
        staging_idx = next((i for i, line in enumerate(lines) if 'staging' in line), -1)
        assert production_idx < staging_idx
