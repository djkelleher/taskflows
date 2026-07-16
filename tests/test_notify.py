"""Tests for sd_notify integration and the Service watchdog."""

import asyncio
import socket

import pytest

from taskflows import DockerContainer, Service, Watchdog
from taskflows import notify as notify_mod
from taskflows.notify import (
    ready,
    sd_notify,
    start_watchdog_pinger,
    status,
    watchdog_interval,
    watchdog_ping,
)


@pytest.fixture
def notify_socket(tmp_path, monkeypatch):
    """A real AF_UNIX datagram socket standing in for systemd's NOTIFY_SOCKET."""
    path = tmp_path / "notify.sock"
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    sock.bind(str(path))
    sock.settimeout(2)
    monkeypatch.setenv("NOTIFY_SOCKET", str(path))
    yield sock
    sock.close()


def test_sd_notify_sends_datagram(notify_socket):
    assert sd_notify("READY=1") is True
    assert notify_socket.recv(1024) == b"READY=1"


def test_helpers_send_expected_states(notify_socket):
    assert ready()
    assert notify_socket.recv(1024) == b"READY=1"
    assert watchdog_ping()
    assert notify_socket.recv(1024) == b"WATCHDOG=1"
    assert status("processing batch 3")
    assert notify_socket.recv(1024) == b"STATUS=processing batch 3"


def test_sd_notify_noop_without_socket(monkeypatch):
    monkeypatch.delenv("NOTIFY_SOCKET", raising=False)
    assert sd_notify("READY=1") is False


def test_sd_notify_survives_dead_socket(tmp_path, monkeypatch):
    monkeypatch.setenv("NOTIFY_SOCKET", str(tmp_path / "gone.sock"))
    assert sd_notify("READY=1") is False


def test_watchdog_interval_from_env(monkeypatch):
    monkeypatch.delenv("WATCHDOG_PID", raising=False)
    monkeypatch.setenv("WATCHDOG_USEC", "30000000")
    assert watchdog_interval() == 30.0

    monkeypatch.setenv("WATCHDOG_PID", "1")  # armed for a different pid
    assert watchdog_interval() is None

    monkeypatch.delenv("WATCHDOG_USEC")
    monkeypatch.delenv("WATCHDOG_PID")
    assert watchdog_interval() is None


@pytest.mark.asyncio
async def test_watchdog_pinger_pings_at_half_interval(notify_socket, monkeypatch):
    monkeypatch.delenv("WATCHDOG_PID", raising=False)
    monkeypatch.setenv("WATCHDOG_USEC", "200000")  # 0.2s -> ping every 0.1s

    task = start_watchdog_pinger()
    assert task is not None
    try:
        loop = asyncio.get_running_loop()
        # First ping is immediate; wait for a second one to prove periodicity
        for _ in range(2):
            data = await loop.run_in_executor(None, notify_socket.recv, 1024)
            assert data == b"WATCHDOG=1"
    finally:
        task.cancel()


@pytest.mark.asyncio
async def test_watchdog_pinger_noop_when_unarmed(monkeypatch):
    monkeypatch.delenv("WATCHDOG_USEC", raising=False)
    assert start_watchdog_pinger() is None


def test_service_watchdog_unit_rendering():
    srv = Service(
        name="wd-render",
        start_command="/bin/sleep 100",
        watchdog=Watchdog(interval_seconds=15),
    )
    rendered = srv.render_unit_files()["taskflows-wd-render.service"]
    assert "Type=notify" in rendered
    assert "NotifyAccess=all" in rendered
    assert "WatchdogSec=15" in rendered
    assert "Restart=on-watchdog" in rendered


def test_service_watchdog_respects_existing_restart_policy():
    srv = Service(
        name="wd-policy",
        start_command="/bin/sleep 100",
        watchdog=Watchdog(interval_seconds=15),
        restart_policy="always",
    )
    rendered = srv.render_unit_files()["taskflows-wd-policy.service"]
    assert "Restart=always" in rendered
    assert "Restart=on-watchdog" not in rendered


def test_service_watchdog_rejects_docker_environment():
    with pytest.raises(ValueError, match="NOTIFY_SOCKET"):
        Service(
            name="wd-docker",
            start_command="x",
            watchdog=Watchdog(),
            environment=DockerContainer(image="python:3.12-slim", name="wd-docker"),
        )


def test_watchdog_yaml_round_trip(tmp_path):
    from taskflows import load_services_from_yaml, save_services_to_yaml

    srv = Service(
        name="wd-yaml",
        start_command="/bin/sleep 100",
        watchdog=Watchdog(interval_seconds=45, notify_access="main"),
    )
    path = tmp_path / "services.yaml"
    save_services_to_yaml([srv], path)
    (loaded,) = load_services_from_yaml(path)
    assert loaded.watchdog.interval_seconds == 45
    assert loaded.watchdog.notify_access == "main"
    assert "WatchdogSec=45" in loaded.render_unit_files()["taskflows-wd-yaml.service"]


def test_notify_module_is_exported():
    assert notify_mod.sd_notify is sd_notify
