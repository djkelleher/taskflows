"""Characterization tests pinning current rendering behavior ahead of refactors.

These tests snapshot (1) rendered systemd unit files for a matrix of Service
configurations and (2) the Docker CLI command / SDK params generated for a
DockerContainer. They intentionally assert on full output so that internal
refactors (unit rendering extraction, docker config deduplication) can prove
they are behavior-preserving.

Unit entries are stored in sets, so directive order within a section is not
deterministic; snapshots normalize by sorting lines within each section.

Regenerate golden files with: pytest tests/test_characterization.py --update-snapshots
"""

import json
from pathlib import Path

import pytest

from taskflows import (
    Calendar,
    CgroupConfig,
    DockerContainer,
    Periodic,
    RestartPolicy,
    Service,
    Venv,
)

HOME = str(Path.home())


def normalize_unit_text(text: str, replacements: dict[str, str] | None = None) -> str:
    """Sort lines within each unit-file section and mask machine-specific paths."""
    replacements = {HOME: "<HOME>", **(replacements or {})}
    for old, new in replacements.items():
        text = text.replace(old, new)
    sections: list[tuple[str, list[str]]] = []
    current_header = None
    current_lines: list[str] = []
    for line in text.splitlines():
        if line.startswith("[") and line.endswith("]"):
            if current_header is not None:
                sections.append((current_header, sorted(current_lines)))
            current_header = line
            current_lines = []
        elif line.strip():
            current_lines.append(line)
    if current_header is not None:
        sections.append((current_header, sorted(current_lines)))
    out = []
    for header, lines in sections:
        out.append(header)
        out.extend(lines)
    return "\n".join(out) + "\n"


@pytest.fixture
def render_units(tmp_path, monkeypatch):
    """Render a Service's unit files into tmp_path and return normalized contents."""

    def render(service: Service, replacements: dict[str, str] | None = None) -> str:
        unit_dir = tmp_path / "units"
        unit_dir.mkdir(exist_ok=True)
        monkeypatch.setattr("taskflows.service.systemd_dir", unit_dir)
        service._write_timer_units()
        service._write_service_units()
        parts = []
        for file in sorted(unit_dir.iterdir()):
            parts.append(f"=== {file.name} ===")
            parts.append(normalize_unit_text(file.read_text(), replacements))
        for file in unit_dir.iterdir():
            file.unlink()
        return "\n".join(parts)

    return render


def test_minimal_service(render_units, snapshot):
    srv = Service(name="snap-minimal", start_command="/bin/echo hello")
    snapshot("minimal_service.txt", render_units(srv))


def test_calendar_service_with_restart_policy(render_units, snapshot):
    srv = Service(
        name="snap-calendar",
        start_command="/bin/echo scheduled",
        start_schedule=Calendar("Mon-Fri 09:00:00"),
        restart_policy=RestartPolicy(condition="on-failure", delay=5),
        timeout=300,
        env={"FOO": "bar", "BAZ": "qux"},
        working_directory="/srv/app",
        description="A scheduled service",
    )
    snapshot("calendar_service.txt", render_units(srv))


def test_periodic_service_with_stop_schedule(render_units, snapshot):
    srv = Service(
        name="snap-periodic",
        start_command="/bin/echo periodic",
        start_schedule=Periodic(start_on="boot", period=3600, relative_to="finish"),
        stop_schedule=Calendar("Sun 03:00:00"),
    )
    snapshot("periodic_service.txt", render_units(srv))


def test_venv_service(render_units, snapshot, tmp_path):
    fake_conda = tmp_path / "conda"
    fake_conda.write_text("#!/bin/sh\n")
    srv = Service(
        name="snap-venv",
        start_command="python -m myapp",
        environment=Venv("myenv", custom_path=fake_conda),
    )
    snapshot("venv_service.txt", render_units(srv, {str(tmp_path): "<TMP>"}))


def test_cgroup_service(render_units, snapshot):
    srv = Service(
        name="snap-cgroup",
        start_command="/bin/echo constrained",
        cgroup_config=CgroupConfig(
            memory_limit=1024**3,
            memory_high=768 * 1024**2,
            cpu_weight=200,
            cpuset_cpus="0-3",
            io_weight=100,
            pids_limit=512,
            oom_score_adj=500,
        ),
    )
    snapshot("cgroup_service.txt", render_units(srv))


def test_service_relations(render_units, snapshot):
    srv = Service(
        name="snap-relations",
        start_command="/bin/echo related",
        start_after=["other-svc"],
        on_success=["next-svc"],
        on_failure=["cleanup-svc"],
        part_of=["parent-svc"],
        conflicts=["rival-svc"],
    )
    snapshot("relations_service.txt", render_units(srv))


def _normalize_docker_params(params: dict) -> str:
    params = dict(params)
    log_config = params.get("log_config")
    if log_config is not None:
        params["log_config"] = {
            "type": str(getattr(log_config, "type", log_config)),
            "config": getattr(log_config, "config", None),
        }
    return json.dumps(params, indent=2, sort_keys=True, default=str)


@pytest.fixture
def container() -> DockerContainer:
    return DockerContainer(
        image="python:3.12-slim",
        name="snap-container",
        command="python -c 'print(1)'",
        environment={"FOO": "bar"},
        network_mode="host",
        shm_size="256m",
        init=True,
        cgroup_config=CgroupConfig(
            memory_limit=1024**3,
            cpu_quota=50000,
            cpuset_cpus="0,1",
            pids_limit=256,
            cap_drop=["ALL"],
        ),
    )


def test_docker_cli_command(container, snapshot):
    snapshot("docker_cli_command.txt", container.docker_run_cli_command() + "\n")


def test_docker_sdk_params(container, snapshot):
    snapshot("docker_sdk_params.json", _normalize_docker_params(container._params()) + "\n")


def test_docker_log_driver_opt_in(container):
    """Log driver is off by default and opt-in per container or via Config."""
    assert "--log-driver" not in container.docker_run_cli_command()
    assert "log_config" not in container._params()

    container.log_driver = "fluentd"
    cli = container.docker_run_cli_command()
    assert "--log-driver fluentd" in cli
    assert "fluentd-address=localhost:24224" in cli
    log_config = container._params()["log_config"]
    assert log_config.type == "fluentd"
    assert log_config.config["fluentd-address"] == "localhost:24224"

    container.log_options = {"fluentd-address": "logs.example.com:24224"}
    assert container._params()["log_config"].config == {"fluentd-address": "logs.example.com:24224"}


def test_docker_log_driver_from_config(container, monkeypatch):
    monkeypatch.setattr("taskflows.docker.config.docker_log_driver", "json-file")
    log_config = container._params()["log_config"]
    assert log_config.type == "json-file"
    assert log_config.config == {}
