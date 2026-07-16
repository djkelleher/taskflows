"""Tests for tf run, tf next, and schedule additions."""

import shutil

import pytest
from click.testing import CliRunner

from taskflows import Calendar, Periodic
from taskflows.admin.cli import cli
from taskflows.schedule import analyze_calendar_spec

systemd_analyze = shutil.which("systemd-analyze") is not None


def test_calendar_randomized_delay_entry():
    cal = Calendar("Mon-Fri 09:00:00", randomized_delay=300)
    assert "RandomizedDelaySec=300" in cal.unit_entries
    assert "RandomizedDelaySec" not in str(Calendar("Mon-Fri 09:00:00").unit_entries)


def test_periodic_randomized_delay_entry():
    per = Periodic(start_on="boot", period=3600, relative_to="finish", randomized_delay=60)
    assert "RandomizedDelaySec=60" in per.unit_entries


@pytest.mark.skipif(not systemd_analyze, reason="systemd-analyze not available")
def test_analyze_calendar_spec_returns_iterations():
    runs = analyze_calendar_spec("Mon-Fri 09:00:00", iterations=3, timezone="UTC")
    assert len(runs) == 3
    assert all("09:00:00" in r for r in runs)


@pytest.mark.skipif(not systemd_analyze, reason="systemd-analyze not available")
def test_analyze_calendar_spec_rejects_garbage():
    with pytest.raises(ValueError):
        analyze_calendar_spec("not a real calendar spec !!!")


@pytest.mark.skipif(not systemd_analyze, reason="systemd-analyze not available")
def test_calendar_next_runs_method():
    runs = Calendar("Sun 03:00:00").next_runs(n=2, timezone="UTC")
    assert len(runs) == 2


def test_tf_run_executes_function(tmp_path, monkeypatch):
    (tmp_path / "myjobs.py").write_text(
        "def add(a, b):\n    return a + b\n",
    )
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    result = runner.invoke(cli, ["run", "myjobs:add", "--kw", "a=20", "--kw", "b=22"])
    assert result.exit_code == 0, result.output
    assert "42" in result.output


def test_tf_run_failure_exits_nonzero(tmp_path, monkeypatch):
    (tmp_path / "myjobs_fail.py").write_text(
        "def boom():\n    raise RuntimeError('nope')\n",
    )
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    result = runner.invoke(cli, ["run", "myjobs_fail:boom"])
    assert result.exit_code != 0


def test_tf_run_rejects_bad_target():
    runner = CliRunner()
    result = runner.invoke(cli, ["run", "not-a-valid-target"])
    assert result.exit_code != 0
    assert "module.path:function" in result.output


def test_tf_run_rejects_missing_function(tmp_path, monkeypatch):
    (tmp_path / "emptymod.py").write_text("")
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    result = runner.invoke(cli, ["run", "emptymod:nothing"])
    assert result.exit_code != 0
    assert "Could not import" in result.output


@pytest.mark.asyncio
async def test_next_runs_renders_calendar_specs(tmp_path, monkeypatch):
    """next_runs reads OnCalendar= lines from installed timer files."""
    from taskflows.admin import core

    timer = tmp_path / "taskflows-demo-job.timer"
    timer.write_text(
        "[Unit]\nDescription=timer for demo-job\n[Timer]\nOnCalendar=Mon-Fri 09:00:00\n"
        "[Install]\nWantedBy=timers.target\n"
    )

    async def fake_get_unit_files(unit_type=None, match=None, states=None):
        return [str(timer)]

    monkeypatch.setattr(core, "get_unit_files", fake_get_unit_files)
    data = await core.next_runs(match="demo-job", iterations=2, as_json=True)
    runs = data["next_runs"]["demo-job"]
    assert len(runs) == 2 if systemd_analyze else runs
