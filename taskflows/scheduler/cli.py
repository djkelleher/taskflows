from __future__ import annotations

import json
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any, Literal

import click

from .daemon import SchedulerDaemon
from .installer import install, uninstall
from .models import ScheduledTask, ScheduleSpec, parse_datetime, utc_now
from .repository import SchedulerRepository
from .runner import run_now
from .supervisor import get_supervisor

HEARTBEAT_TIMEOUT_SECONDS = 5


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


def _parse_environment(values: tuple[str, ...]) -> dict[str, str]:
    environment: dict[str, str] = {}
    for value in values:
        key, separator, item = value.partition("=")
        if not separator or not key:
            raise click.BadParameter(f"environment value must be KEY=VALUE: {value!r}")
        environment[key] = item
    return environment


@click.group("schedule")
def schedule_cli() -> None:
    """Manage portable, short-lived scheduled commands."""


@schedule_cli.command("add")
@click.argument("name")
@click.argument("command", nargs=-1, required=True)
@click.option("--at", "run_at", help="One-time ISO timestamp including an offset or Z.")
@click.option("--interval", type=float, help="Repeat every N seconds.")
@click.option("--cron", help="Five-field cron expression, for example '0 9 * * 1-5'.")
@click.option("--timezone", default="UTC", show_default=True, help="IANA time zone for cron.")
@click.option("--cwd", type=click.Path(file_okay=False), help="Working directory.")
@click.option("--env", "environment", multiple=True, help="Environment KEY=VALUE; repeatable.")
@click.option("--timeout", type=float, help="Terminate the process tree after N seconds.")
@click.option("--misfire-grace", type=int, default=3600, show_default=True)
@click.option("--max-instances", type=click.IntRange(min=1), default=1, show_default=True)
@click.option("--no-coalesce", is_flag=True, help="Run every retained occurrence after downtime.")
@click.option("--disabled", is_flag=True, help="Create without activating the schedule.")
@click.option("--replace", is_flag=True, help="Replace an existing task with this name.")
def add_schedule(
    name: str,
    command: tuple[str, ...],
    run_at: str | None,
    interval: float | None,
    cron: str | None,
    timezone: str,
    cwd: str | None,
    environment: tuple[str, ...],
    timeout: float | None,
    misfire_grace: int,
    max_instances: int,
    no_coalesce: bool,
    disabled: bool,
    replace: bool,
) -> None:
    selected = sum(value is not None for value in (run_at, interval, cron))
    if selected != 1:
        raise click.UsageError("provide exactly one of --at, --interval, or --cron")
    try:
        if run_at is not None:
            spec = ScheduleSpec.once(run_at)
        elif interval is not None:
            spec = ScheduleSpec.interval(interval, start_at=utc_now(), timezone=timezone)
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
            environment=_parse_environment(environment),
            misfire_grace_time=misfire_grace,
            coalesce=not no_coalesce,
            max_instances=max_instances,
        )
        repository = _repository()
        saved = repository.add(task, replace_existing=replace)
    except (TypeError, ValueError) as exc:
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
    rows = [
        {
            "id": task.id,
            "name": task.name,
            "enabled": task.enabled,
            "schedule": task.schedule.describe(),
            "next_run_at": task.next_run_at.isoformat() if task.next_run_at else None,
            "command": list(task.command),
        }
        for task in tasks
    ]
    if as_json:
        click.echo(json.dumps(rows, indent=2))
        return
    if not rows:
        click.echo("No scheduled tasks")
        return
    for row in rows:
        state = "enabled" if row["enabled"] else "disabled"
        next_run = row["next_run_at"] or "-"
        click.echo(f"{row['name']}\t{state}\t{next_run}\t{row['schedule']}")


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
