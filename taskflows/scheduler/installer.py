from __future__ import annotations

import os
import plistlib
import shlex
import subprocess
import sys
from pathlib import Path

from taskflows.common import services_data_dir

LINUX_UNIT_NAME = "taskflows-scheduler.service"
MACOS_LABEL = "com.taskflows.scheduler"
WINDOWS_TASK_FOLDER = "Taskflows"
WINDOWS_TASK_NAME = "Scheduler"


def _home_dir() -> Path:
    return Path.home()


def _daemon_command() -> list[str]:
    return [sys.executable, "-m", "taskflows.scheduler.daemon"]


def _run(command: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(command, check=check, capture_output=True, text=True)
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or str(exc)).strip()
        raise RuntimeError(f"{command[0]} failed: {detail}") from exc


def install_linux() -> Path:
    unit_dir = _home_dir() / ".config" / "systemd" / "user"
    unit_dir.mkdir(parents=True, exist_ok=True)
    unit_path = unit_dir / LINUX_UNIT_NAME
    command = shlex.join(_daemon_command())
    data_dir = services_data_dir.resolve()
    environment_assignment = str(data_dir).replace("\\", "\\\\").replace('"', '\\"')
    content = f"""[Unit]
Description=Taskflows portable scheduler
After=default.target

[Service]
Type=simple
ExecStart={command}
Environment="TASKFLOWS_DATA_DIR={environment_assignment}"
Restart=on-failure
RestartSec=2

[Install]
WantedBy=default.target
"""
    unit_path.write_text(content)
    _run(["systemctl", "--user", "daemon-reload"])
    _run(["systemctl", "--user", "enable", "--now", LINUX_UNIT_NAME])
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
    log_dir = services_data_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    plist_path = agents_dir / f"{MACOS_LABEL}.plist"
    definition = {
        "Label": MACOS_LABEL,
        "ProgramArguments": _daemon_command(),
        "EnvironmentVariables": {"TASKFLOWS_DATA_DIR": str(services_data_dir.resolve())},
        "RunAtLoad": True,
        "KeepAlive": {"SuccessfulExit": False},
        "ProcessType": "Background",
        "StandardOutPath": str(log_dir / "scheduler.stdout.log"),
        "StandardErrorPath": str(log_dir / "scheduler.stderr.log"),
    }
    with plist_path.open("wb") as stream:
        plistlib.dump(definition, stream)
    domain = f"gui/{uid}"
    _run(["launchctl", "bootout", domain, str(plist_path)], check=False)
    _run(["launchctl", "bootstrap", domain, str(plist_path)])
    _run(["launchctl", "enable", f"{domain}/{MACOS_LABEL}"])
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
    definition.RegistrationInfo.Description = "Taskflows portable scheduler daemon"
    definition.Principal.LogonType = 3  # TASK_LOGON_INTERACTIVE_TOKEN
    definition.Principal.RunLevel = 0  # TASK_RUNLEVEL_LUA (least privilege)
    settings = definition.Settings
    settings.Enabled = True
    settings.StartWhenAvailable = True
    settings.ExecutionTimeLimit = "PT0S"
    settings.RestartCount = 3
    settings.RestartInterval = "PT1M"
    settings.MultipleInstances = 2  # TASK_INSTANCES_IGNORE_NEW

    definition.Triggers.Create(9)  # TASK_TRIGGER_LOGON
    action = definition.Actions.Create(0)  # TASK_ACTION_EXEC
    action.Path = sys.executable
    action.Arguments = subprocess.list2cmdline(["-m", "taskflows.scheduler.daemon"])
    action.WorkingDirectory = str(_home_dir())
    # TASK_CREATE_OR_UPDATE, current interactive user, no stored password.
    folder.RegisterTaskDefinition(WINDOWS_TASK_NAME, definition, 6, "", "", 3)
    folder.GetTask(WINDOWS_TASK_NAME).Run("")


def uninstall_windows() -> None:
    import win32com.client

    scheduler = win32com.client.Dispatch("Schedule.Service")
    scheduler.Connect()
    try:
        folder = scheduler.GetFolder(f"\\{WINDOWS_TASK_FOLDER}")
        folder.GetTask(WINDOWS_TASK_NAME).Stop(0)
        folder.DeleteTask(WINDOWS_TASK_NAME, 0)
    except Exception:
        return


def install() -> Path | None:
    if sys.platform == "win32":
        install_windows()
        return None
    if sys.platform == "darwin":
        return install_macos()
    if sys.platform.startswith("linux"):
        return install_linux()
    raise NotImplementedError(f"scheduler installation is unsupported on {sys.platform}")


def uninstall() -> None:
    if sys.platform == "win32":
        uninstall_windows()
    elif sys.platform == "darwin":
        uninstall_macos()
    elif sys.platform.startswith("linux"):
        uninstall_linux()
    else:
        raise NotImplementedError(f"scheduler installation is unsupported on {sys.platform}")
