"""Tests for the missed-run (dead-man switch) monitor."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from taskflows import MissedRunAlert, Service
from taskflows import monitor as monitor_mod
from taskflows.alerts import SlackChannel
from taskflows.monitor import (
    build_monitor_service,
    check_missed_runs,
    check_service,
    load_monitor_configs,
    write_monitor_config,
)

NOW = datetime(2026, 7, 16, 12, 0, 0, tzinfo=UTC)


@pytest.fixture
def dst():
    return MagicMock(spec=SlackChannel)


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(monitor_mod, "services_data_dir", tmp_path)
    return tmp_path


def test_missed_run_alert_rejects_non_msgdst():
    with pytest.raises(TypeError, match="MsgDst"):
        MissedRunAlert(send_to="not-a-destination")


def test_monitor_config_round_trip(data_dir):
    config = MissedRunAlert(
        send_to=SlackChannel(channel="alerts"), grace_seconds=600, alert_on_failure=False
    )
    write_monitor_config("nightly-etl", config)
    loaded = load_monitor_configs()
    assert set(loaded) == {"nightly-etl"}
    assert loaded["nightly-etl"].grace_seconds == 600
    assert loaded["nightly-etl"].alert_on_failure is False
    assert loaded["nightly-etl"].send_to[0].channel == "alerts"


def _usec(dt: datetime) -> int:
    return int(dt.timestamp() * 1_000_000)


def _unit(name: str, active_state: str) -> dict:
    return {"unit_name": name, "active_state": active_state}


async def _run_check(config, units, next_start=None):
    with (
        patch.object(monitor_mod, "check_service", wraps=check_service),
        patch("taskflows.systemd.get_units", new_callable=AsyncMock, return_value=units),
        patch(
            "taskflows.systemd.get_schedule_info",
            new_callable=AsyncMock,
            return_value={"Next Start": next_start},
        ),
    ):
        return await check_service("my-job", config, NOW)


@pytest.mark.asyncio
async def test_healthy_service_reports_no_problems(dst):
    config = MissedRunAlert(send_to=dst)
    units = [
        _unit("taskflows-my-job.timer", "active"),
        _unit("taskflows-my-job.service", "inactive"),
    ]
    problems = await _run_check(config, units, next_start=NOW + timedelta(hours=1))
    assert problems == []


def test_schedule_timestamp_normalizer_accepts_datetime_and_legacy_microseconds():
    assert monitor_mod._usec_to_datetime(NOW) == NOW
    assert monitor_mod._usec_to_datetime(_usec(NOW)) == NOW


@pytest.mark.asyncio
async def test_missing_timer_detected(dst):
    config = MissedRunAlert(send_to=dst)
    problems = await _run_check(config, [])
    assert any("not loaded" in p for p in problems)


@pytest.mark.asyncio
async def test_inactive_timer_detected(dst):
    config = MissedRunAlert(send_to=dst)
    units = [_unit("taskflows-my-job.timer", "inactive")]
    problems = await _run_check(config, units)
    assert any("inactive" in p for p in problems)


@pytest.mark.asyncio
async def test_overdue_run_detected(dst):
    config = MissedRunAlert(send_to=dst, grace_seconds=300)
    units = [_unit("taskflows-my-job.timer", "active")]
    problems = await _run_check(config, units, next_start=NOW - timedelta(minutes=30))
    assert any("overdue" in p for p in problems)


@pytest.mark.asyncio
async def test_within_grace_not_reported(dst):
    config = MissedRunAlert(send_to=dst, grace_seconds=3600)
    units = [_unit("taskflows-my-job.timer", "active")]
    problems = await _run_check(config, units, next_start=NOW - timedelta(minutes=30))
    assert problems == []


@pytest.mark.asyncio
async def test_failed_last_run_detected(dst):
    config = MissedRunAlert(send_to=dst)
    units = [
        _unit("taskflows-my-job.timer", "active"),
        _unit("taskflows-my-job.service", "failed"),
    ]
    problems = await _run_check(config, units, next_start=NOW + timedelta(hours=1))
    assert any("failed" in p for p in problems)

    config_no_fail = MissedRunAlert(send_to=dst, alert_on_failure=False)
    problems = await _run_check(config_no_fail, units, next_start=NOW + timedelta(hours=1))
    assert problems == []


@pytest.mark.asyncio
async def test_check_missed_runs_sends_alerts(data_dir, dst):
    write_monitor_config("broken-job", MissedRunAlert(send_to=SlackChannel(channel="alerts")))

    with (
        patch.object(
            monitor_mod,
            "check_service",
            new_callable=AsyncMock,
            return_value=["timer unit is not loaded"],
        ),
        patch.object(monitor_mod, "send_alert", new_callable=AsyncMock) as send,
    ):
        results = await check_missed_runs()

    assert results == {"broken-job": ["timer unit is not loaded"]}
    assert send.called
    assert send.call_args.kwargs["subject"] == "Missed-run alert: broken-job"


@pytest.mark.asyncio
async def test_check_missed_runs_quiet_when_healthy(data_dir, dst):
    write_monitor_config("good-job", MissedRunAlert(send_to=SlackChannel(channel="alerts")))

    with (
        patch.object(monitor_mod, "check_service", new_callable=AsyncMock, return_value=[]),
        patch.object(monitor_mod, "send_alert", new_callable=AsyncMock) as send,
    ):
        results = await check_missed_runs()

    assert results == {}
    assert not send.called


def test_service_yaml_round_trip_with_missed_run_alert(tmp_path):
    from taskflows import load_services_from_yaml, save_services_to_yaml

    srv = Service(
        name="monitored-job",
        start_command="/bin/echo hi",
        alert_on_missed_run=MissedRunAlert(
            send_to=SlackChannel(channel="alerts"), grace_seconds=900
        ),
    )
    path = tmp_path / "services.yaml"
    save_services_to_yaml([srv], path)
    (loaded,) = load_services_from_yaml(path)
    assert loaded.alert_on_missed_run.grace_seconds == 900
    assert loaded.alert_on_missed_run.send_to[0].channel == "alerts"


def test_build_monitor_service():
    srv = build_monitor_service(period_seconds=120)
    assert srv.name == "monitor"
    assert "monitor check" in srv.start_command
    rendered = srv.render_unit_files()["taskflows-monitor.timer"]
    assert "OnUnitInactiveSec=120s" in rendered
