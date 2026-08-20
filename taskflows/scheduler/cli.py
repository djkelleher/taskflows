from __future__ import annotations

import json
import re
from datetime import timedelta
from pathlib import Path
from typing import Any, Literal

import click
from dotenv import dotenv_values

from taskflows.exceptions import RevisionConflict

from .daemon import SchedulerDaemon
from .models import (
    DEFAULT_TASK_TIMEOUT_SECONDS,
    ScheduledTask,
    ScheduleSpec,
    schedule_preview,
    utc_now,
)
from .repository import SchedulerRepository
from .runner import enqueue_now, run_now
from .status import (
    diagnose_scheduler,
    operate_scheduler,
    runtime_status,
    scheduler_status,
)
from .supervisor import get_supervisor

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
@click.option(
    "--timeout",
    type=DURATION,
    default=None,
    show_default=f"{DEFAULT_TASK_TIMEOUT_SECONDS:g}s",
    help="Terminate after a duration, e.g. 90s or 5m.",
)
@click.option(
    "--no-timeout",
    is_flag=True,
    help="Allow an unbounded command (persistent work should normally use a Service).",
)
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
    no_timeout: bool,
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
    if no_timeout and timeout is not None:
        raise click.UsageError("--no-timeout cannot be combined with --timeout")
    try:
        if run_at is not None:
            spec = ScheduleSpec.once(run_at, timezone=timezone)
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
            timeout=None if no_timeout else timeout or DEFAULT_TASK_TIMEOUT_SECONDS,
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
    if saved.enabled and not runtime_status(repository).healthy:
        click.echo(
            "Warning: the scheduler daemon is not responding; run 'tf scheduler ensure'.",
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
    except (KeyError, RuntimeError) as exc:
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


@schedule_cli.command("preview")
@click.argument("identifier")
@click.option("--count", type=click.IntRange(min=1, max=1000), default=5, show_default=True)
@click.option(
    "--from",
    "from_time",
    help="Offset-aware ISO timestamp to preview from; defaults to now.",
)
@click.option("--json", "as_json", is_flag=True)
def preview_schedule(identifier: str, count: int, from_time: str | None, as_json: bool) -> None:
    """Preview real trigger occurrences, including DST and time-zone effects."""
    try:
        task = _repository().resolve(identifier)
        data = schedule_preview(task, after=from_time, count=count)
    except (KeyError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc
    if as_json:
        click.echo(json.dumps(data, indent=2))
        return
    if not data["occurrences"]:
        click.echo("No future occurrences")
        return
    for occurrence in data["occurrences"]:
        if data["timezone"] == "UTC":
            click.echo(occurrence["utc"])
        else:
            click.echo(f"{occurrence['local']}\t{occurrence['utc']} UTC")


def _set_enabled(identifier: str, enabled: bool) -> None:
    repository = _repository()
    try:
        task = repository.set_enabled(identifier, enabled)
    except KeyError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"{'Enabled' if enabled else 'Disabled'} {task.name}")
    if enabled and not runtime_status(repository).healthy:
        click.echo(
            "Warning: the scheduler daemon is not responding; run 'tf scheduler ensure'.",
            err=True,
        )


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
    try:
        repository.delete(task.id, expected_revision=task.revision)
    except RevisionConflict as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"Removed {task.name}")


@schedule_cli.command("run")
@click.argument("identifier")
@click.option("--wait/--no-wait", default=True, show_default=True)
def run_schedule(identifier: str, wait: bool) -> None:
    try:
        if not wait:
            repository = _repository()
            if not runtime_status(repository).healthy:
                raise RuntimeError(
                    "the scheduler daemon is not responding; run 'tf scheduler ensure' "
                    "or omit --no-wait"
                )
            handle = enqueue_now(repository.database_path, identifier)
            click.echo(f"Accepted run {handle.id} ({handle.status})")
            return
        exit_code = run_now(_repository().database_path, identifier)
    except (KeyError, RuntimeError) as exc:
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


@schedule_cli.command("prune")
@click.option(
    "--older-than",
    type=DURATION,
    default="30d",
    show_default=True,
    help="Delete terminal attempts older than this duration.",
)
@click.option(
    "--keep-latest",
    type=click.IntRange(min=0),
    default=10,
    show_default=True,
    help="Always retain this many newest attempts per task definition.",
)
@click.option("--dry-run", is_flag=True, help="Count eligible attempts without deleting them.")
@click.option("--yes", is_flag=True, help="Do not ask for confirmation.")
def prune_schedule_history(
    older_than: float,
    keep_latest: int,
    dry_run: bool,
    yes: bool,
) -> None:
    """Apply run-history and captured-log retention safely."""
    repository = _repository()
    cutoff = utc_now() - timedelta(seconds=older_than)
    preview = repository.prune_history(
        before=cutoff,
        keep_latest=keep_latest,
        dry_run=True,
    )
    if dry_run:
        click.echo(f"Would delete {preview.runs_deleted} terminal run(s)")
        return
    if preview.runs_deleted == 0:
        click.echo("No run history eligible for pruning")
        return
    if not yes and not click.confirm(
        f"Delete {preview.runs_deleted} terminal run(s) and their captured logs?"
    ):
        return
    result = repository.prune_history(before=cutoff, keep_latest=keep_latest)
    click.echo(f"Deleted {result.runs_deleted} run(s) and {result.log_files_deleted} log file(s)")
    for error in result.log_errors:
        click.echo(f"Warning: {error}", err=True)


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
            with path.open("rb") as log_file:
                log_file.seek(0, 2)
                size = log_file.tell()
                log_file.seek(max(size - 1024 * 1024, 0))
                content = log_file.read(1024 * 1024).decode(errors="replace").splitlines()
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
@click.option("--wait/--no-wait", default=True, show_default=True)
@click.option("--timeout", type=DURATION, default=15.0, show_default="15s")
def install_daemon(wait: bool, timeout: float) -> None:
    """Install and start one native OS-managed scheduler daemon."""
    try:
        status = operate_scheduler(
            "install", _repository(), get_supervisor(), wait=wait, timeout=timeout
        )
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc
    path = status.supervisor.definition_path
    click.echo(f"Scheduler installed{f' at {path}' if path else ''}")


@scheduler_cli.command("ensure")
@click.option("--wait/--no-wait", default=True, show_default=True)
@click.option("--timeout", type=DURATION, default=15.0, show_default="15s")
def ensure_daemon(wait: bool, timeout: float) -> None:
    """Install, repair, or start the scheduler only when needed."""
    try:
        status = operate_scheduler(
            "ensure", _repository(), get_supervisor(), wait=wait, timeout=timeout
        )
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"Scheduler ready ({status.supervisor.backend})")


@scheduler_cli.command("uninstall")
@click.option("--wait/--no-wait", default=True, show_default=True)
@click.option("--timeout", type=DURATION, default=15.0, show_default="15s")
def uninstall_daemon(wait: bool, timeout: float) -> None:
    """Stop and remove the native scheduler daemon definition."""
    try:
        operate_scheduler("uninstall", _repository(), get_supervisor(), wait=wait, timeout=timeout)
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo("Scheduler uninstalled")


def _supervisor_operation(
    operation: Literal["start", "stop", "restart"], *, wait: bool, timeout: float
) -> None:
    try:
        operate_scheduler(
            operation,
            _repository(),
            get_supervisor(),
            wait=wait,
            timeout=timeout,
        )
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc
    completed = {"start": "started", "stop": "stopped", "restart": "restarted"}
    click.echo(f"Scheduler {completed[operation]}")


@scheduler_cli.command("start")
@click.option("--wait/--no-wait", default=True, show_default=True)
@click.option("--timeout", type=DURATION, default=15.0, show_default="15s")
def start_daemon(wait: bool, timeout: float) -> None:
    """Start the installed native scheduler daemon."""
    _supervisor_operation("start", wait=wait, timeout=timeout)


@scheduler_cli.command("stop")
@click.option("--wait/--no-wait", default=True, show_default=True)
@click.option("--timeout", type=DURATION, default=15.0, show_default="15s")
def stop_daemon(wait: bool, timeout: float) -> None:
    """Stop the installed native scheduler daemon without uninstalling it."""
    _supervisor_operation("stop", wait=wait, timeout=timeout)


@scheduler_cli.command("restart")
@click.option("--wait/--no-wait", default=True, show_default=True)
@click.option("--timeout", type=DURATION, default=15.0, show_default="15s")
def restart_daemon(wait: bool, timeout: float) -> None:
    """Restart the installed native scheduler daemon."""
    _supervisor_operation("restart", wait=wait, timeout=timeout)


@scheduler_cli.command("status")
@click.option("--json", "as_json", is_flag=True)
@click.pass_context
def daemon_status(context: click.Context, as_json: bool) -> None:
    try:
        status = scheduler_status(_repository(), get_supervisor())
    except Exception as exc:
        raise click.ClickException(f"could not inspect scheduler status: {exc}") from exc
    if as_json:
        click.echo(json.dumps(status.to_dict(), indent=2))
    else:
        click.echo(f"{status.state} ({status.supervisor.backend}: {status.supervisor.state})")
        click.echo(
            f"Registry: {status.database_path} "
            f"({status.enabled_task_count}/{status.task_count} tasks enabled)"
        )
        if status.queued_occurrence_count or status.running_run_count:
            click.echo(
                f"Active runs: {status.running_run_count} running, "
                f"{status.queued_occurrence_count} queued"
            )
        if status.runtime.heartbeat_at:
            age = status.runtime.heartbeat_age_seconds
            age_text = (
                "invalid"
                if age is None
                else f"{-age:.1f}s in the future"
                if age < 0
                else f"{age:.1f}s ago"
            )
            click.echo(
                f"Heartbeat: {age_text} from {status.runtime.hostname or 'unknown host'} "
                f"(pid {status.runtime.pid or '-'})"
            )
        if status.supervisor.detail and status.state != "running":
            click.echo(f"Native detail: {status.supervisor.detail}")
        if status.supervisor.log_hint and status.state != "running":
            click.echo(f"Native logs: {status.supervisor.log_hint}")
    if status.state != "running":
        context.exit(1)


@scheduler_cli.command("doctor")
@click.option("--json", "as_json", is_flag=True)
@click.pass_context
def scheduler_doctor(context: click.Context, as_json: bool) -> None:
    """Run actionable native, registry, heartbeat, and dispatch checks."""
    try:
        status, checks = diagnose_scheduler(_repository(), get_supervisor())
    except Exception as exc:
        raise click.ClickException(f"could not diagnose scheduler: {exc}") from exc
    if as_json:
        click.echo(
            json.dumps(
                {
                    "status": status.to_dict(),
                    "checks": [check.to_dict() for check in checks],
                },
                indent=2,
            )
        )
    else:
        labels = {"ok": "OK", "warning": "WARN", "error": "ERROR"}
        for check in checks:
            click.echo(f"[{labels[check.level]}] {check.name}: {check.message}")
            if check.remedy:
                click.echo(f"       Fix: {check.remedy}")
    if any(check.level == "error" for check in checks):
        context.exit(1)
