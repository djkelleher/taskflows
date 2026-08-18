"""Dependency management for cloud function deployments.

This module handles dependency resolution, packaging, and Docker-based builds
for consistent deployment packages.
"""

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from ..common import logger


class DependencyManager:
    """Manages dependencies for cloud function deployments."""

    def __init__(self, python_version: str = "3.11"):
        self.python_version = python_version
        self.cache_dir = Path.home() / ".taskflows" / "lambda-deps-cache"
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def build_deployment_package(
        self,
        requirements: list[str],
        include_files: list[Path] | None = None,
        use_docker: bool = False,
    ) -> bytes:
        """Build a deployment package with all dependencies.

        Args:
            requirements: List of pip package names
            include_files: Additional files to include
            use_docker: Use Docker for consistent builds (recommended for production)

        Returns:
            Bytes of the deployment package (zip file)
        """
        if use_docker:
            return self._build_with_docker(requirements, include_files)
        else:
            return self._build_locally(requirements, include_files)

    def _build_locally(
        self,
        requirements: list[str],
        include_files: list[Path] | None = None,
    ) -> bytes:
        """Build package locally using pip."""
        import io
        import zipfile

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            deps_dir = tmp_path / "package"
            deps_dir.mkdir()

            # Install dependencies
            if requirements:
                logger.info(f"Installing dependencies: {requirements}")
                self._install_requirements(requirements, deps_dir)

            # Create zip
            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
                # Add dependencies
                for root, _dirs, files in os.walk(deps_dir):
                    for file in files:
                        file_path = Path(root) / file
                        if file == ".lock" or file_path.suffix == ".pyc":
                            continue
                        arcname = file_path.relative_to(deps_dir)
                        zip_file.write(file_path, arcname)

                # Add additional files
                if include_files:
                    for file_path in include_files:
                        if file_path.exists():
                            zip_file.write(file_path, file_path.name)

            return zip_buffer.getvalue()

    def _build_with_docker(
        self,
        requirements: list[str],
        include_files: list[Path] | None = None,
    ) -> bytes:
        """Build package using Docker for consistent environment.

        This ensures the package is built in the same environment as Lambda.
        """
        import io
        import zipfile

        docker_available = shutil.which("docker") is not None
        if not docker_available:
            logger.warning("Docker not available, falling back to local build")
            return self._build_locally(requirements, include_files)

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)

            # Write requirements.txt
            if requirements:
                requirements_file = tmp_path / "requirements.txt"
                requirements_file.write_text("\n".join(requirements))

            # Create Dockerfile
            dockerfile = tmp_path / "Dockerfile"
            dockerfile.write_text(f"""
FROM public.ecr.aws/lambda/python:{self.python_version}

COPY requirements.txt .
RUN pip install --target /asset -r requirements.txt
""")

            # Build Docker image
            logger.info("Building dependencies in Docker...")
            subprocess.run(
                ["docker", "build", "-t", "taskflows-builder", str(tmp_path)],
                check=True,
                capture_output=True,
            )

            # Extract dependencies
            container_id = subprocess.check_output(
                ["docker", "create", "taskflows-builder"],
                text=True,
            ).strip()

            try:
                # Copy dependencies from container
                output_dir = tmp_path / "output"
                output_dir.mkdir()

                subprocess.run(
                    ["docker", "cp", f"{container_id}:/asset", str(output_dir)],
                    check=True,
                )

                # Create zip
                zip_buffer = io.BytesIO()
                with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
                    # Add dependencies
                    asset_dir = output_dir / "asset"
                    for root, _dirs, files in os.walk(asset_dir):
                        for file in files:
                            file_path = Path(root) / file
                            arcname = file_path.relative_to(asset_dir)
                            zip_file.write(file_path, arcname)

                    # Add additional files
                    if include_files:
                        for file_path in include_files:
                            if file_path.exists():
                                zip_file.write(file_path, file_path.name)

                return zip_buffer.getvalue()

            finally:
                # Cleanup
                subprocess.run(["docker", "rm", container_id], capture_output=True)

    def create_layer_package(
        self,
        requirements: list[str],
        runtime: str = "python3.11",
    ) -> bytes:
        """Create a Lambda Layer package with proper structure.

        Args:
            requirements: List of pip packages
            runtime: Python runtime version

        Returns:
            Bytes of the layer zip file
        """
        import io
        import zipfile

        python_version = runtime.replace("python", "")  # e.g., "3.11"

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)

            # Lambda layer structure: python/lib/pythonX.Y/site-packages/
            layer_dir = tmp_path / "python" / "lib" / f"python{python_version}" / "site-packages"
            layer_dir.mkdir(parents=True)

            # Install dependencies
            if requirements:
                logger.info(f"Building layer with: {requirements}")
                self._install_requirements(requirements, layer_dir)

            # Create zip
            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
                for root, _dirs, files in os.walk(tmp_path):
                    for file in files:
                        file_path = Path(root) / file
                        arcname = file_path.relative_to(tmp_path)
                        zip_file.write(file_path, arcname)

            return zip_buffer.getvalue()

    def parse_requirements_file(self, requirements_file: Path) -> list[str]:
        """Parse a requirements.txt file.

        Args:
            requirements_file: Path to requirements.txt

        Returns:
            List of package specifications
        """
        if not requirements_file.exists():
            return []

        requirements = []
        for line in requirements_file.read_text().splitlines():
            line = line.strip()
            # Skip comments and empty lines
            if line and not line.startswith("#"):
                requirements.append(line)

        return requirements

    @staticmethod
    def _install_requirements(requirements: list[str], target: Path) -> None:
        """Install requirements into ``target`` without shell interpolation."""
        if shutil.which("uv"):
            command = [
                "uv",
                "pip",
                "install",
                "--python",
                sys.executable,
                "--target",
                str(target),
                "--upgrade",
                *requirements,
            ]
        else:
            command = [
                sys.executable,
                "-m",
                "pip",
                "install",
                "--target",
                str(target),
                "--upgrade",
                *requirements,
            ]
        subprocess.run(command, check=True, capture_output=True, text=True)

    def detect_imports(self, source_code: str) -> set[str]:
        """Detect imported packages from source code.

        Args:
            source_code: Python source code

        Returns:
            Set of package names (best effort)
        """
        import ast
        import re

        imports = set()

        try:
            tree = ast.parse(source_code)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        imports.add(alias.name.split(".")[0])
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imports.add(node.module.split(".")[0])
        except SyntaxError:
            # Fallback to regex
            import_pattern = r"^\s*(?:import|from)\s+([a-zA-Z0-9_]+)"
            imports.update(re.findall(import_pattern, source_code, re.MULTILINE))

        # Filter stdlib modules (simplified)
        stdlib = {
            "os",
            "sys",
            "re",
            "json",
            "time",
            "datetime",
            "pathlib",
            "typing",
            "dataclasses",
            "collections",
            "itertools",
            "functools",
            "io",
            "math",
            "random",
            "string",
            "asyncio",
            "threading",
            "multiprocessing",
            "subprocess",
            "logging",
            "argparse",
            "configparser",
            "urllib",
            "http",
            "email",
            "html",
            "xml",
            "csv",
            "sqlite3",
            "pickle",
            "hashlib",
            "hmac",
            "secrets",
            "uuid",
            "base64",
            "binascii",
            "struct",
            "socket",
            "ssl",
            "tempfile",
            "shutil",
            "glob",
            "fnmatch",
            "traceback",
            "warnings",
            "contextlib",
            "abc",
            "enum",
            "decimal",
            "fractions",
            "statistics",
            "copy",
            "pprint",
        }

        return imports - stdlib
