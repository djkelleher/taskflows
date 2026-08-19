"""Common lifecycle for the native process manager on each operating system."""

from __future__ import annotations

import os
import subprocess
import sys
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol

from . import installer as native

SupervisorState = Literal["starting", "running", "stopped", "failed", "unknown", "not-installed"]


@dataclass(frozen=True)
class SupervisorStatus:
    """Platform-neutral state returned by every native daemon supervisor."""

    backend: Literal["systemd", "launchd", "windows-task-scheduler"]
    installed: bool
    state: SupervisorState
    definition_path: str | None = None
    detail: str | None = None


class SchedulerSupervisor(Protocol):
    """Common lifecycle implemented by each per-user native supervisor."""

    def install(self) -> Path | None: ...

    def uninstall(self) -> None: ...

    def start(self) -> None: ...

    def stop(self) -> None: ...

    def restart(self) -> None: ...

    def status(self) -> SupervisorStatus: ...


def _completed_detail(result: subprocess.CompletedProcess[str]) -> str | None:
    detail = (result.stdout or result.stderr or "").strip()
    return detail or None


class SystemdSupervisor:
    """Manage the scheduler as a systemd user service."""

    @property
    def definition_path(self) -> Path:
        return native._home_dir() / ".config" / "systemd" / "user" / native.LINUX_UNIT_NAME

    def install(self) -> Path:
        return native.install_linux()

    def uninstall(self) -> None:
        native.uninstall_linux()

    def start(self) -> None:
        native._run(["systemctl", "--user", "start", native.LINUX_UNIT_NAME])

    def stop(self) -> None:
        native._run(["systemctl", "--user", "stop", native.LINUX_UNIT_NAME])

    def restart(self) -> None:
        native._run(["systemctl", "--user", "restart", native.LINUX_UNIT_NAME])

    def status(self) -> SupervisorStatus:
        installed = self.definition_path.exists()
        if not installed:
            return SupervisorStatus(
                backend="systemd",
                installed=False,
                state="not-installed",
                definition_path=str(self.definition_path),
            )
        try:
            result = native._run(
                ["systemctl", "--user", "is-active", native.LINUX_UNIT_NAME], check=False
            )
        except OSError as exc:
            return SupervisorStatus(
                backend="systemd",
                installed=True,
                state="unknown",
                definition_path=str(self.definition_path),
                detail=str(exc),
            )
        detail = _completed_detail(result)
        state: SupervisorState
        if result.returncode == 0 and detail == "active":
            state = "running"
        elif detail in {"activating", "reloading"}:
            state = "starting"
        elif detail == "failed":
            state = "failed"
        else:
            state = "stopped"
        return SupervisorStatus(
            backend="systemd",
            installed=True,
            state=state,
            definition_path=str(self.definition_path),
            detail=detail,
        )


class LaunchdSupervisor:
    """Manage the scheduler as a per-user macOS LaunchAgent."""

    @property
    def definition_path(self) -> Path:
        return native._home_dir() / "Library" / "LaunchAgents" / f"{native.MACOS_LABEL}.plist"

    @property
    def domain(self) -> str:
        return f"gui/{os.getuid()}"

    @property
    def service_target(self) -> str:
        return f"{self.domain}/{native.MACOS_LABEL}"

    def install(self) -> Path:
        return native.install_macos()

    def uninstall(self) -> None:
        native.uninstall_macos()

    def start(self) -> None:
        if not self.definition_path.exists():
            raise RuntimeError("the Taskflows scheduler LaunchAgent is not installed")
        native._run(["launchctl", "enable", self.service_target])
        loaded = native._run(["launchctl", "print", self.service_target], check=False)
        if loaded.returncode != 0:
            native._run(["launchctl", "bootstrap", self.domain, str(self.definition_path)])
        native._run(["launchctl", "kickstart", "-k", self.service_target])

    def stop(self) -> None:
        native._run(["launchctl", "bootout", self.domain, str(self.definition_path)], check=False)
        native._run(["launchctl", "disable", self.service_target])

    def restart(self) -> None:
        # ``kickstart`` alone fails after ``stop`` because bootout unloads the
        # agent.  Route restart through start so the common lifecycle has the
        # same stopped -> running behavior on every operating system.
        self.start()

    def status(self) -> SupervisorStatus:
        installed = self.definition_path.exists()
        if not installed:
            return SupervisorStatus(
                backend="launchd",
                installed=False,
                state="not-installed",
                definition_path=str(self.definition_path),
            )
        try:
            result = native._run(["launchctl", "print", self.service_target], check=False)
        except OSError as exc:
            return SupervisorStatus(
                backend="launchd",
                installed=True,
                state="unknown",
                definition_path=str(self.definition_path),
                detail=str(exc),
            )
        detail = _completed_detail(result)
        state: SupervisorState = "stopped"
        if result.returncode == 0 and detail and "state = running" in detail:
            state = "running"
        return SupervisorStatus(
            backend="launchd",
            installed=True,
            state=state,
            definition_path=str(self.definition_path),
            detail=detail,
        )


def _windows_registered_task() -> Any | None:
    import win32com.client

    scheduler = win32com.client.Dispatch("Schedule.Service")
    scheduler.Connect()
    try:
        folder = scheduler.GetFolder(f"\\{native.WINDOWS_TASK_FOLDER}")
        return folder.GetTask(native.WINDOWS_TASK_NAME)
    except Exception:
        return None


class WindowsTaskSupervisor:
    """Manage the scheduler through the current user's Task Scheduler folder."""

    def install(self) -> None:
        native.install_windows()

    def uninstall(self) -> None:
        native.uninstall_windows()

    def start(self) -> None:
        task = _windows_registered_task()
        if task is None:
            raise RuntimeError("the Taskflows scheduler task is not installed")
        task.Run("")

    def stop(self) -> None:
        task = _windows_registered_task()
        if task is None:
            raise RuntimeError("the Taskflows scheduler task is not installed")
        with suppress(Exception):
            task.Stop(0)

    def restart(self) -> None:
        self.stop()
        self.start()

    def status(self) -> SupervisorStatus:
        try:
            task = _windows_registered_task()
        except Exception as exc:
            return SupervisorStatus(
                backend="windows-task-scheduler",
                installed=False,
                state="unknown",
                detail=str(exc),
            )
        if task is None:
            return SupervisorStatus(
                backend="windows-task-scheduler", installed=False, state="not-installed"
            )
        task_state = int(getattr(task, "State", 0))
        # TASK_STATE_RUNNING=4, READY=3, QUEUED=2, DISABLED=1, UNKNOWN=0.
        state: SupervisorState = "running" if task_state == 4 else "stopped"
        if task_state == 2:
            state = "starting"
        if task_state == 0:
            state = "unknown"
        return SupervisorStatus(
            backend="windows-task-scheduler",
            installed=True,
            state=state,
            detail=f"Task Scheduler state {task_state}",
        )


def get_supervisor(platform_name: str | None = None) -> SchedulerSupervisor:
    """Return the native per-user supervisor for a Python platform name."""

    platform_name = platform_name or sys.platform
    if platform_name == "win32":
        return WindowsTaskSupervisor()
    if platform_name == "darwin":
        return LaunchdSupervisor()
    if platform_name.startswith("linux"):
        return SystemdSupervisor()
    raise NotImplementedError(f"scheduler supervision is unsupported on {platform_name}")
