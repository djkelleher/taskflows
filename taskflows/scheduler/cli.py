from __future__ import annotations

import json
import re
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import click
from dotenv import dotenv_values

from taskflows.exceptions import RevisionConflict

from .daemon import SchedulerDaemon
from .installer import install, uninstall
from .models import ScheduledTask, ScheduleSpec, parse_datetime, utc_now
from .repository import SchedulerRepository
from .runner import run_now
from .supervisor import get_supervisor

HEARTBEAT_TIMEOUT_SECONDS = 5

_DURATION_PATTERN = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*([a-zA-Z]+)?\s*$")
_DURATION_UNITS = {
    None: 1.0,
    "s": 1.0,
    "sec": 1.0,
    "second": 1.0,
    "seconds": 1.0,
    "m": 60.0,
    "min": 60.0,
    "minute": 60.0,
    "minutes": 60.0,
    "h": 3600.0,
    "hr": 3600.0,
    "hour": 3600.0,
    "hours": 3600.0,
    "d": 86400.0,
    "day": 86400.0,
    "days": 86400.0,
    "w": 604800.0,
    "week": 604800.0,
    "weeks": 604800.0,
}


class DurationType(click.ParamType):
    """Click value accepting seconds or compact human-readable durations."""

    name = "duration"

    def convert(
        self,
        value: Any,
        param: click.Parameter | None,
        ctx: click.Context | None,
    ) -> float | None:
        if value is None:
            return None
        match = _DURATION_PATTERN.fullmatch(str(value))
        if match is None:
            self.fail(f"{value!r} is not a duration (examples: 30, 5m, 1.5h)", param, ctx)
        number, unit = match.groups()
        multiplier = _DURATION_UNITS.get(unit.lower() if unit else None)
        if multiplier is None:
            self.fail(f"unknown duration unit in {value!r}", param, ctx)
        seconds = float(number) * multiplier
        if seconds <= 0:
            self.fail("duration must be greater than zero", param, ctx)
        return seconds


DURATION = DurationType()


def _repository() -> SchedulerRepository:
    return SchedulerRepository()


def _daemon_runtime_state(repository: SchedulerRepository) -> dict[str, Any]:
    state = repository.daemon_state() or {}
    heartbeat_value = state.get("heartbeat_at")
    if heartbeat_value:
        try:
            heartbeat = parse_datetime(heartbeat_value)
            age = (datetime.now(UTC) - heartbeat.astimezone(UTC)).total_seconds()
        except (TypeError, ValueError):
            age = None
        state["heartbeat_age_seconds"] = age
        state["healthy"] = age is not None and 0 <= age < HEARTBEAT_TIMEOUT_SECONDS
    else:
        state["healthy"] = False
    return state


def _parse_environment(values: tuple[str, ...], env_files: tuple[Path, ...] = ()) -> dict[str, str]:
    environment: dict[str, str] = {}

    def assign(key: str, value: str) -> None:
        # Definitions are portable to Windows, where environment names are
        # case-insensitive. Later files and explicit values therefore replace
        # aliases such as ``Path``/``PATH`` rather than creating a definition
        # whose behavior would differ by platform.
        for existing in tuple(environment):
            if existing.casefold() == key.casefold():
                environment.pop(existing)
        environment[key] = value

    for env_file in env_files:
        try:
            loaded = dotenv_values(env_file, interpolate=False)
        except (OSError, UnicodeError) as exc:
            raise click.BadParameter(f"could not read environment file {env_file}: {exc}") from exc
        missing = [key for key, value in loaded.items() if value is None]
        if missing:
            raise click.BadParameter(
                f"environment file {env_file} has values missing '=': {', '.join(missing)}"
            )
        for key, value in loaded.items():
            if value is not None:
                assign(key, value)
    for value in values:
        key, separator, item = value.partition("=")
        if not separator or not key:
            raise click.BadParameter(f"environment value must be KEY=VALUE: {value!r}")
        # Explicit command-line values override files, matching common dotenv
        # and container CLI behavior.
        assign(key, item)
    return environment


@click.group("schedule")
def schedule_cli() -> None:
    """Manage portable, short-lived scheduled commands."""


@schedule_cli.command("add")
@click.argument("name")
@click.argument("command", nargs=-1, required=True)
@click.option("--at", "run_at", help="One-time ISO timestamp including an offset or Z.")
@click.option("--interval", type=DURATION, help="Repeat interval, e.g. 30, 5m, or 1.5h.")
@click.option("--start-at", help="Optional offset-aware first run for an interval schedule.")
@click.option("--cron", help="Five-field cron expression, for example '0 9 * * 1-5'.")
@click.option("--timezone", default="UTC", show_default=True, help="IANA time zone for cron.")
@click.option("--cwd", type=click.Path(file_okay=False), help="Working directory.")
@click.option(
    "--env-file",
    "env_files",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    multiple=True,
    help="Load environment values from a dotenv file; repeatable.",
)
@click.option("--env", "environment", multiple=True, help="Environment KEY=VALUE; repeatable.")
@click.option("--timeout", type=DURATION, help="Terminate after a duration, e.g. 90s or 5m.")
@click.option("--misfire-grace", type=int, default=3600, show_default=True)
@click.option("--max-instances", type=click.IntRange(min=1), default=1, show_default=True)
@click.option("--no-coalesce", is_flag=True, help="Run every retained occurrence after downtime.")
@click.option("--disabled", is_flag=True, help="Create without activating the schedule.")
@click.option("--replace", is_flag=True, help="Replace an existing task with this name.")
@click.option(
    "--revision",
    type=click.IntRange(min=1),
    help="Only replace the definition if it still has this revision.",
)
def add_schedule(
    name: str,
    command: tuple[str, ...],
    run_at: str | None,
    interval: float | None,
    start_at: str | None,
    cron: str | None,
    timezone: str,
    cwd: str | None,
    env_files: tuple[Path, ...],
    environment: tuple[str, ...],
    timeout: float | None,
    misfire_grace: int,
    max_instances: int,
    no_coalesce: bool,
    disabled: bool,
    replace: bool,
    revision: int | None,
) -> None:
    selected = sum(value is not None for value in (run_at, interval, cron))
    if selected != 1:
        raise click.UsageError("provide exactly one of --at, --interval, or --cron")
    if start_at is not None and interval is None:
        raise click.UsageError("--start-at can only be used with --interval")
    if revision is not None and not replace:
        raise click.UsageError("--revision can only be used with --replace")
    try:
        if run_at is not None:
            spec = ScheduleSpec.once(run_at)
        elif interval is not None:
            spec = ScheduleSpec.interval(
                interval, start_at=start_at or utc_now(), timezone=timezone
            )
        else:
            assert cron is not None
            spec = ScheduleSpec.cron(cron, timezone=timezone)
        task = ScheduledTask.create(
            name=name,
            command=command,
            schedule=spec,
            enabled=not disabled,
            timeout=timeout,
            cwd=cwd,
            environment=_parse_environment(environment, env_files),
            misfire_grace_time=misfire_grace,
            coalesce=not no_coalesce,
            max_instances=max_instances,
        )
        repository = _repository()
        saved = repository.add(
            task,
            replace_existing=replace,
            expected_revision=revision,
        )
    except (RevisionConflict, TypeError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"Scheduled {saved.name} ({saved.schedule.describe()})")
    if saved.enabled and not _daemon_runtime_state(repository)["healthy"]:
        click.echo(
            "Warning: the scheduler daemon is not responding; run "
            "'tf scheduler install' or 'tf scheduler start'.",
            err=True,
        )


@schedule_cli.command("list")
@click.argument("match", required=False)
@click.option("--json", "as_json", is_flag=True)
def list_schedules(match: str | None, as_json: bool) -> None:
    repository = _repository()
    tasks = repository.list(match=match)
    rows = [task.to_public_dict() for task in tasks]
    if as_json:
        click.echo(json.dumps(rows, indent=2))
        return
    if not rows:
        click.echo("No scheduled tasks")
        return
    for row in rows:
        state = "enabled" if row["enabled"] else "disabled"
        next_run = row["next_run_at"] or "-"
        click.echo(f"{row['name']}\t{state}\t{next_run}\t{row['schedule']['description']}")


@schedule_cli.command("show")
@click.argument("identifier")
@click.option("--json", "as_json", is_flag=True)
def show_schedule(identifier: str, as_json: bool) -> None:
    """Show one definition without exposing environment values."""
    try:
        data = _repository().resolve(identifier).to_public_dict()
    except KeyError as exc:
        raise click.ClickException(str(exc)) from exc
    if as_json:
        click.echo(json.dumps(data, indent=2))
        return
    click.echo(f"Name: {data['name']}")
    click.echo(f"ID: {data['id']}")
    click.echo(f"Enabled: {'yes' if data['enabled'] else 'no'}")
    click.echo(f"Schedule: {data['schedule']['description']}")
    click.echo(f"Next run: {data['next_run_at'] or '-'}")
    click.echo(f"Command: {json.dumps(data['command'])}")
    click.echo(f"Working directory: {data['cwd'] or '-'}")
    click.echo(f"Timeout: {data['timeout'] if data['timeout'] is not None else '-'}")
    names = data["environment_names"]
    click.echo(f"Environment names: {', '.join(names) if names else '-'}")
    click.echo(f"Revision: {data['revision']}")


def _set_enabled(identifier: str, enabled: bool) -> None:
    try:
        task = _repository().set_enabled(identifier, enabled)
    except KeyError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"{'Enabled' if enabled else 'Disabled'} {task.name}")


@schedule_cli.command("enable")
@click.argument("identifier")
def enable_schedule(identifier: str) -> None:
    _set_enabled(identifier, True)


@schedule_cli.command("disable")
@click.argument("identifier")
def disable_schedule(identifier: str) -> None:
    _set_enabled(identifier, False)


@schedule_cli.command("remove")
@click.argument("identifier")
@click.option("--yes", is_flag=True, help="Do not ask for confirmation.")
def remove_schedule(identifier: str, yes: bool) -> None:
    repository = _repository()
    try:
        task = repository.resolve(identifier)
    except KeyError as exc:
        raise click.ClickException(str(exc)) from exc
    if not yes and not click.confirm(f"Remove scheduled task {task.name}?"):
        return
    repository.delete(task.id)
    click.echo(f"Removed {task.name}")


@schedule_cli.command("run")
@click.argument("identifier")
def run_schedule(identifier: str) -> None:
    try:
        exit_code = run_now(_repository().database_path, identifier)
    except KeyError as exc:
        raise click.ClickException(str(exc)) from exc
    if exit_code is None:
        raise click.ClickException("task was not started because its overlap limit was reached")
    if exit_code != 0:
        raise click.ClickException(f"command exited with status {exit_code}")


@schedule_cli.command("history")
@click.argument("identifier", required=False)
@click.option("--limit", type=click.IntRange(min=1, max=10000), default=50, show_default=True)
@click.option("--json", "as_json", is_flag=True)
def schedule_history(identifier: str | None, limit: int, as_json: bool) -> None:
    try:
        rows = _repository().history(identifier, limit=limit)
    except KeyError as exc:
        raise click.ClickException(str(exc)) from exc
    if as_json:
        click.echo(json.dumps(rows, indent=2))
        return
    if not rows:
        click.echo("No runs")
    for row in rows:
        click.echo(
            f"{row['task_name']}\t{row['status']}\t{row['started_at'] or row['scheduled_for']}"
            f"\texit={row['exit_code'] if row['exit_code'] is not None else '-'}"
        )


def _safe_log_path(repository: SchedulerRepository, value: str) -> Path:
    root = (repository.database_path.parent / "runs").resolve()
    path = Path(value).resolve()
    if not path.is_relative_to(root):
        raise click.ClickException("refusing to read a run log outside the Taskflows run directory")
    return path


@schedule_cli.command("logs")
@click.argument("identifier")
@click.option(
    "--stream",
    type=click.Choice(["stdout", "stderr", "both"]),
    default="both",
    show_default=True,
)
@click.option("--lines", type=click.IntRange(min=1, max=100000), default=200, show_default=True)
def schedule_logs(identifier: str, stream: str, lines: int) -> None:
    """Print captured output from the most recent run."""
    repository = _repository()
    rows = repository.history(identifier, limit=1)
    if not rows:
        raise click.ClickException(f"no runs found for scheduled task {identifier!r}")
    row = rows[0]
    fields = (
        ("stdout", row.get("stdout_path")),
        ("stderr", row.get("stderr_path")),
    )
    selected = [(name, value) for name, value in fields if stream in (name, "both")]
    printed = False
    for name, value in selected:
        if not value:
            continue
        path = _safe_log_path(repository, value)
        try:
            content = path.read_text(errors="replace").splitlines()
        except OSError as exc:
            raise click.ClickException(f"could not read {name} log {path}: {exc}") from exc
        if stream == "both":
            click.echo(f"==> {name} <==")
        click.echo("\n".join(content[-lines:]))
        printed = True
    if not printed:
        raise click.ClickException("the latest run has no captured log files")


@click.group("scheduler")
def scheduler_cli() -> None:
    """Manage the portable scheduler daemon."""


@scheduler_cli.command("run")
def run_daemon() -> None:
    """Run the scheduler in the foreground."""
    SchedulerDaemon().run_forever()


@scheduler_cli.command("install")
def install_daemon() -> None:
    """Install and start one native OS-managed scheduler daemon."""
    try:
        path = install()
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"Scheduler installed{f' at {path}' if path else ''}")


@scheduler_cli.command("uninstall")
def uninstall_daemon() -> None:
    """Stop and remove the native scheduler daemon definition."""
    try:
        uninstall()
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo("Scheduler uninstalled")


def _supervisor_operation(operation: Literal["start", "stop", "restart"]) -> None:
    try:
        supervisor = get_supervisor()
        operations = {
            "start": supervisor.start,
            "stop": supervisor.stop,
            "restart": supervisor.restart,
        }
        operations[operation]()
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc
    completed = {"start": "started", "stop": "stopped", "restart": "restarted"}
    click.echo(f"Scheduler {completed[operation]}")


@scheduler_cli.command("start")
def start_daemon() -> None:
    """Start the installed native scheduler daemon."""
    _supervisor_operation("start")


@scheduler_cli.command("stop")
def stop_daemon() -> None:
    """Stop the installed native scheduler daemon without uninstalling it."""
    _supervisor_operation("stop")


@scheduler_cli.command("restart")
def restart_daemon() -> None:
    """Restart the installed native scheduler daemon."""
    _supervisor_operation("restart")


@scheduler_cli.command("status")
@click.option("--json", "as_json", is_flag=True)
@click.pass_context
def daemon_status(context: click.Context, as_json: bool) -> None:
    try:
        native = asdict(get_supervisor().status())
    except Exception as exc:
        native = {
            "backend": "unsupported",
            "installed": False,
            "state": "unknown",
            "definition_path": None,
            "detail": str(exc),
        }
    state = _daemon_runtime_state(_repository())
    state["supervisor"] = native
    if as_json:
        click.echo(json.dumps(state, indent=2))
    else:
        if state["healthy"]:
            click.echo(f"running ({native['backend']}: {native['state']})")
        else:
            click.echo(f"stopped or unresponsive ({native['backend']}: {native['state']})")
    if not state["healthy"]:
        context.exit(1)
