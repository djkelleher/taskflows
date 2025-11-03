"""Dependency management for cloud function deployments.

This module handles dependency resolution, packaging, and Docker-based builds
for consistent deployment packages.
"""

import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import List, Optional, Set

from ..common import logger


class DependencyManager:
    """Manages dependencies for cloud function deployments."""

    def __init__(self, python_version: str = "3.11"):
        self.python_version = python_version
        self.cache_dir = Path.home() / ".taskflows" / "lambda-deps-cache"
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def build_deployment_package(
        self,
        requirements: List[str],
        include_files: Optional[List[Path]] = None,
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
        requirements: List[str],
        include_files: Optional[List[Path]] = None,
    ) -> bytes:
        """Build package locally using pip."""
        import io
        import zipfile

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            deps_dir = tmp_path / "python"
            deps_dir.mkdir()

            # Install dependencies
            if requirements:
                logger.info(f"Installing dependencies: {requirements}")
                subprocess.run(
                    [
                        "pip",
                        "install",
                        "--target",
                        str(deps_dir),
                        "--upgrade",
                        *requirements,
                    ],
                    check=True,
                    capture_output=True,
                )

            # Create zip
            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
                # Add dependencies
                for root, dirs, files in os.walk(deps_dir):
                    for file in files:
                        file_path = Path(root) / file
                        arcname = file_path.relative_to(tmp_path)
                        zip_file.write(file_path, arcname)

                # Add additional files
                if include_files:
                    for file_path in include_files:
                        if file_path.exists():
                            zip_file.write(file_path, file_path.name)

            return zip_buffer.getvalue()

    def _build_with_docker(
        self,
        requirements: List[str],
        include_files: Optional[List[Path]] = None,
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
                    for root, dirs, files in os.walk(asset_dir):
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
        requirements: List[str],
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
                subprocess.run(
                    [
                        "pip",
                        "install",
                        "--target",
                        str(layer_dir),
                        "--upgrade",
                        *requirements,
                    ],
                    check=True,
                    capture_output=True,
                )

            # Create zip
            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
                for root, dirs, files in os.walk(tmp_path):
                    for file in files:
                        file_path = Path(root) / file
                        arcname = file_path.relative_to(tmp_path)
                        zip_file.write(file_path, arcname)

            return zip_buffer.getvalue()

    def parse_requirements_file(self, requirements_file: Path) -> List[str]:
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

    def detect_imports(self, source_code: str) -> Set[str]:
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
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
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
