"""Runtime execution environments for service commands."""

import shlex
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Venv:
    env_name: str
    custom_path: str | Path | None = None

    @staticmethod
    def _run_command(exe: Path, env_name: str, command: str) -> str:
        runner = shlex.quote(str(exe))
        quoted_env_name = shlex.quote(env_name)
        live_output_flag = Venv._live_output_flag(exe)
        executable_separator = "--"
        live_output_part = f" {live_output_flag}" if live_output_flag else ""

        return (
            f"{runner} run -n {quoted_env_name}{live_output_part} {executable_separator} {command}"
        )

    @staticmethod
    def _live_output_flag(exe: Path) -> str:
        try:
            completed = subprocess.run(
                [str(exe), "run", "--help"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            help_text = f"{completed.stdout}\n{completed.stderr}"
        except (OSError, subprocess.SubprocessError):
            help_text = ""

        if "--attach" in help_text:
            return "-a ''"
        if "--no-capture-output" in help_text:
            return "--no-capture-output"
        if "--live-stream" in help_text:
            return "--live-stream"
        if exe.name in {"mamba", "micromamba"}:
            return ""
        return "--no-capture-output"

    def create_env_command(self, command: str) -> str:
        # If custom path is provided, use it directly
        if self.custom_path:
            exe = Path(self.custom_path)
            if not exe.is_file():
                raise FileNotFoundError(f"Custom executable not found: {exe}")
            return self._run_command(exe, self.env_name, command)

        # Prefer runners already available on PATH before checking common
        # installation locations.
        path_exes = tuple(
            Path(executable)
            for name in ("micromamba", "mamba", "conda")
            if (executable := shutil.which(name))
        )
        home = Path.home()
        exes = path_exes + (
            # Mamba distributions
            home.joinpath("mambaforge", "bin", "mamba"),
            home.joinpath("miniforge3", "bin", "mamba"),
            home.joinpath("micromamba", "bin", "micromamba"),
            home.joinpath(".local", "bin", "micromamba"),
            # Conda distributions
            home.joinpath("miniconda3", "condabin", "conda"),
            home.joinpath("miniconda3", "bin", "conda"),
            home.joinpath("anaconda3", "condabin", "conda"),
            home.joinpath("anaconda3", "bin", "conda"),
            home.joinpath("miniconda", "condabin", "conda"),
            home.joinpath("miniconda", "bin", "conda"),
            home.joinpath("anaconda", "condabin", "conda"),
            home.joinpath("anaconda", "bin", "conda"),
            # Common system-wide locations
            Path("/opt/conda/bin/conda"),
            Path("/opt/miniconda3/bin/conda"),
            Path("/opt/anaconda3/bin/conda"),
            # Pyenv conda installations
            home.joinpath(".pyenv", "versions", "miniconda3-latest", "bin", "conda"),
            home.joinpath(".pyenv", "versions", "anaconda3-latest", "bin", "conda"),
        )
        for exe in exes:
            if exe.is_file():
                return self._run_command(exe, self.env_name, command)

        # Service definitions and serialized configs must remain portable to
        # machines where the environment runner is installed later. Use the
        # conventional executable name and let systemd surface a clear runtime
        # error if it is still unavailable when the service starts.
        return self._run_command(Path("conda"), self.env_name, command)
