from __future__ import annotations

import hashlib
import json
import os
import plistlib
import subprocess
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from contextvars import ContextVar
from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from typing import Any

from taskflows.common import secure_write_text, services_data_dir

LINUX_UNIT_NAME = "taskflows-scheduler.service"
MACOS_LABEL = "com.taskflows.scheduler"
WINDOWS_TASK_FOLDER = "Taskflows"
WINDOWS_TASK_NAME = "Scheduler"

# Task Scheduler COM constants. Keeping the names beside the numeric values
# makes this module readable without importing platform-only modules on POSIX.
_TASK_ACTION_EXEC = 0
_TASK_CREATE_OR_UPDATE = 6
_TASK_INSTANCES_IGNORE_NEW = 2
_TASK_LOGON_INTERACTIVE_TOKEN = 3
_TASK_RUNLEVEL_LUA = 0
_TASK_TRIGGER_LOGON = 9
_COMMAND_TIMEOUT: ContextVar[float] = ContextVar("scheduler_command_timeout", default=15.0)


@dataclass(frozen=True)
class WindowsTaskDefinition:
    """Canonical Windows registration shared by installation and drift checks."""

    user_id: str
    source: str
    command: tuple[str, ...]
    working_directory: str


def _windows_definition() -> WindowsTaskDefinition:
    windows_api: Any = import_module("win32api")
    return WindowsTaskDefinition(
        user_id=str(windows_api.GetUserNameEx(windows_api.NameSamCompatible)),
        source=definition_fingerprint(),
        command=tuple(_daemon_command()),
        working_directory=str(_home_dir()),
    )


@contextmanager
def operation_timeout(seconds: float) -> Iterator[None]:
    token = _COMMAND_TIMEOUT.set(seconds)
    try:
        yield
    finally:
        _COMMAND_TIMEOUT.reset(token)


def current_operation_timeout() -> float:
    """Return the active lifecycle deadline for subprocess and COM adapters."""

    return _COMMAND_TIMEOUT.get()


def _home_dir() -> Path:
    return Path.home()


def _daemon_command() -> list[str]:
    database_path = (services_data_dir / "scheduler.sqlite3").resolve()
    return [
        sys.executable,
        "-m",
        "taskflows.scheduler.daemon",
        "--database",
        str(database_path),
    ]


def definition_fingerprint() -> str:
    """Fingerprint the interpreter, registry and daemon invocation we expect."""

    payload = json.dumps(
        {
            "command": _daemon_command(),
            "data_dir": str(services_data_dir.resolve()),
            "version": 1,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(payload).hexdigest()


def _systemd_quote(value: str) -> str:
    """Quote one literal systemd argument without relying on shell syntax."""

    escaped: list[str] = []
    for character in value.replace("%", "%%"):
        if character == "\\":
            escaped.append("\\\\")
        elif character == '"':
            escaped.append('\\"')
        elif character == "\n":
            escaped.append("\\n")
        elif character == "\r":
            escaped.append("\\r")
        elif character == "\t":
            escaped.append("\\t")
        elif ord(character) < 32 or ord(character) == 127:
            escaped.append(f"\\x{ord(character):02x}")
        else:
            escaped.append(character)
    return f'"{"".join(escaped)}"'


def _linux_unit_content() -> str:
    """Return the complete systemd definition expected by the supervisor."""

    # systemd expands percent specifiers even in quoted values and uses its own
    # C-style command parser rather than a POSIX shell. Render every argument
    # independently so spaces, quotes, control characters and literal percent
    # signs cannot change unit structure or invocation boundaries.
    command = " ".join(_systemd_quote(part) for part in _daemon_command())
    working_directory = _systemd_quote(str(_home_dir()))
    data_dir = services_data_dir.resolve()
    environment_assignment = _systemd_quote(f"TASKFLOWS_DATA_DIR={data_dir}")
    return f"""[Unit]
Description=Taskflows portable scheduler
X-Taskflows-Definition={definition_fingerprint()}
After=default.target

[Service]
Type=simple
ExecStart={command}
WorkingDirectory={working_directory}
Environment={environment_assignment}
Restart=on-failure
RestartSec=2

[Install]
WantedBy=default.target
"""


def _macos_definition() -> dict[str, Any]:
    """Return the complete LaunchAgent definition expected by the supervisor."""

    data_dir = services_data_dir.resolve()
    log_dir = data_dir / "logs"
    return {
        "Label": MACOS_LABEL,
        "TaskflowsDefinitionFingerprint": definition_fingerprint(),
        "ProgramArguments": _daemon_command(),
        "EnvironmentVariables": {"TASKFLOWS_DATA_DIR": str(data_dir)},
        "RunAtLoad": True,
        "KeepAlive": {"SuccessfulExit": False},
        "ProcessType": "Background",
        "WorkingDirectory": str(_home_dir()),
        "StandardOutPath": str(log_dir / "scheduler.stdout.log"),
        "StandardErrorPath": str(log_dir / "scheduler.stderr.log"),
    }


def _wait_for_windows_task_stop(task: Any) -> None:
    """Wait until Task Scheduler has finished an asynchronous stop request."""

    # Fake/third-party COM wrappers may not expose State. In that case there is
    # nothing useful to poll and the outer combined lifecycle wait remains the
    # final readiness check.
    if not hasattr(task, "State"):
        return
    deadline = time.monotonic() + current_operation_timeout()
    while int(task.State) in {2, 4}:  # queued or running
        if time.monotonic() >= deadline:
            raise TimeoutError(
                f"Windows scheduler task did not stop within {current_operation_timeout():g}s"
            )
        time.sleep(0.05)


def _run(command: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            command,
            check=check,
            capture_output=True,
            text=True,
            timeout=_COMMAND_TIMEOUT.get(),
        )
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or str(exc)).strip()
        raise RuntimeError(f"{command[0]} failed: {detail}") from exc
    except subprocess.TimeoutExpired as exc:
        raise TimeoutError(
            f"{command[0]} did not finish within {_COMMAND_TIMEOUT.get():g}s"
        ) from exc


def install_linux() -> Path:
    unit_dir = _home_dir() / ".config" / "systemd" / "user"
    unit_dir.mkdir(parents=True, exist_ok=True)
    unit_path = unit_dir / LINUX_UNIT_NAME
    # systemd may reload the unit while an upgrade is in progress.  Keep the
    # definition owner-readable only and replace it atomically, just as the
    # macOS LaunchAgent definition is handled below.
    secure_write_text(unit_path, _linux_unit_content())
    _run(["systemctl", "--user", "daemon-reload"])
    # ``enable --now`` does not restart an already-active unit.  Restart after
    # enabling so reinstalling also applies an updated interpreter, database
    # path, or environment without waiting for the next login.
    _run(["systemctl", "--user", "enable", LINUX_UNIT_NAME])
    _run(["systemctl", "--user", "restart", LINUX_UNIT_NAME])
    return unit_path


def uninstall_linux() -> None:
    _run(["systemctl", "--user", "disable", "--now", LINUX_UNIT_NAME], check=False)
    unit_path = _home_dir() / ".config" / "systemd" / "user" / LINUX_UNIT_NAME
    unit_path.unlink(missing_ok=True)
    _run(["systemctl", "--user", "daemon-reload"], check=False)


def install_macos() -> Path:
    uid = os.getuid()
    agents_dir = _home_dir() / "Library" / "LaunchAgents"
    agents_dir.mkdir(parents=True, exist_ok=True)
    data_dir = services_data_dir.resolve()
    data_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(data_dir, 0o700)
    log_dir = data_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(log_dir, 0o700)
    plist_path = agents_dir / f"{MACOS_LABEL}.plist"
    definition = _macos_definition()
    # launchd can observe this file at login while an upgrade is writing it.
    # Replace a complete owner-only plist atomically instead of exposing a
    # partial definition.
    plist = plistlib.dumps(definition, fmt=plistlib.FMT_XML).decode("utf-8")
    secure_write_text(plist_path, plist)
    domain = f"gui/{uid}"
    _run(["launchctl", "bootout", domain, str(plist_path)], check=False)
    # `disable` state persists independently of the plist. Re-enable before
    # bootstrap so reinstall also repairs a manually disabled agent.
    _run(["launchctl", "enable", f"{domain}/{MACOS_LABEL}"])
    _run(["launchctl", "bootstrap", domain, str(plist_path)])
    _run(["launchctl", "kickstart", "-k", f"{domain}/{MACOS_LABEL}"])
    return plist_path


def uninstall_macos() -> None:
    plist_path = _home_dir() / "Library" / "LaunchAgents" / f"{MACOS_LABEL}.plist"
    _run(["launchctl", "bootout", f"gui/{os.getuid()}", str(plist_path)], check=False)
    plist_path.unlink(missing_ok=True)


def install_windows() -> None:
    """Register a per-user logon task through the Task Scheduler COM API.

    Running in the interactive user's profile ensures the daemon and CLI use
    the same SQLite registry. A LocalSystem service would execute user commands
    with excessive privileges and silently use a different home directory.
    """
    import win32com.client

    scheduler = win32com.client.Dispatch("Schedule.Service")
    scheduler.Connect()
    root = scheduler.GetFolder("\\")
    try:
        folder = root.GetFolder(f"\\{WINDOWS_TASK_FOLDER}")
    except Exception:
        folder = root.CreateFolder(WINDOWS_TASK_FOLDER)

    definition = scheduler.NewTask(0)
    expected = _windows_definition()
    definition.RegistrationInfo.Description = "Taskflows portable scheduler daemon"
    definition.RegistrationInfo.Source = expected.source
    # A SAM-compatible name scopes both the task principal and logon trigger
    # to the installing user. An unscoped logon trigger fires for every user.
    user_id = expected.user_id
    definition.Principal.UserId = user_id
    definition.Principal.LogonType = _TASK_LOGON_INTERACTIVE_TOKEN
    definition.Principal.RunLevel = _TASK_RUNLEVEL_LUA
    settings = definition.Settings
    settings.Enabled = True
    settings.StartWhenAvailable = True
    # The scheduler is a lightweight supervisor and must not disappear when a
    # laptop starts or switches to battery power.
    settings.DisallowStartIfOnBatteries = False
    settings.StopIfGoingOnBatteries = False
    settings.RunOnlyIfIdle = False
    settings.RunOnlyIfNetworkAvailable = False
    settings.AllowDemandStart = True
    settings.ExecutionTimeLimit = "PT0S"
    settings.RestartCount = 3
    settings.RestartInterval = "PT1M"
    settings.MultipleInstances = _TASK_INSTANCES_IGNORE_NEW

    trigger = definition.Triggers.Create(_TASK_TRIGGER_LOGON)
    trigger.UserId = user_id
    trigger.Enabled = True
    action = definition.Actions.Create(_TASK_ACTION_EXEC)
    command = list(expected.command)
    action.Path = command[0]
    action.Arguments = subprocess.list2cmdline(command[1:])
    action.WorkingDirectory = expected.working_directory
    # Apply an updated interpreter/database path immediately instead of leaving
    # an old instance running until the next login.
    try:
        previous_task = folder.GetTask(WINDOWS_TASK_NAME)
        previous_task.Stop(0)
    except Exception:
        pass
    else:
        _wait_for_windows_task_stop(previous_task)
    # Current interactive user, with no stored password.
    folder.RegisterTaskDefinition(
        WINDOWS_TASK_NAME,
        definition,
        _TASK_CREATE_OR_UPDATE,
        user_id,
        "",
        _TASK_LOGON_INTERACTIVE_TOKEN,
    )
    folder.GetTask(WINDOWS_TASK_NAME).Run("")


def uninstall_windows() -> None:
    import win32com.client

    scheduler = win32com.client.Dispatch("Schedule.Service")
    scheduler.Connect()
    try:
        folder = scheduler.GetFolder(f"\\{WINDOWS_TASK_FOLDER}")
        task = folder.GetTask(WINDOWS_TASK_NAME)
    except Exception:
        return
    # Stopping an already-finished instance may fail on some Task Scheduler
    # versions. Deletion must still be attempted.
    with suppress(Exception):
        task.Stop(0)
    folder.DeleteTask(WINDOWS_TASK_NAME, 0)


def install() -> Path | None:
    from .supervisor import get_supervisor

    return get_supervisor().install()


def uninstall() -> None:
    from .supervisor import get_supervisor

    get_supervisor().uninstall()
