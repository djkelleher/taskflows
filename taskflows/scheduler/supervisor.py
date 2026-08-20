"""Common lifecycle for the native process manager on each operating system."""

from __future__ import annotations

import os
import plistlib
import re
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
    # Backward-compatible defaults for third-party supervisors. Built-in
    # backends always pass explicit values, including None when inspection fails.
    automatic: bool | None = True
    registration_valid: bool | None = True
    definition_fingerprint: str | None = None
    definition_path: str | None = None
    last_exit_code: int | None = None
    log_hint: str | None = None
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

    @property
    def log_hint(self) -> str:
        daemon_log = native.services_data_dir.resolve() / "logs" / "scheduler-daemon.log"
        return f"{daemon_log} or journalctl --user -u {native.LINUX_UNIT_NAME} -n 200"

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
                automatic=False,
                registration_valid=False,
                definition_path=str(self.definition_path),
                log_hint=self.log_hint,
            )
        fingerprint: str | None = None
        registration_valid: bool | None = None
        try:
            definition = self.definition_path.read_text()
            match = re.search(r"^X-Taskflows-Definition=(.+)$", definition, re.MULTILINE)
            fingerprint = match.group(1).strip() if match else None
            registration_valid = fingerprint == native.definition_fingerprint()
        except OSError:
            registration_valid = None
        try:
            result = native._run(
                ["systemctl", "--user", "is-active", native.LINUX_UNIT_NAME], check=False
            )
        except (OSError, TimeoutError) as exc:
            return SupervisorStatus(
                backend="systemd",
                installed=True,
                state="unknown",
                automatic=None,
                registration_valid=None,
                definition_path=str(self.definition_path),
                log_hint=self.log_hint,
                detail=str(exc),
            )
        detail = _completed_detail(result)
        try:
            enabled_result = native._run(
                ["systemctl", "--user", "is-enabled", native.LINUX_UNIT_NAME], check=False
            )
        except (OSError, TimeoutError):
            enabled_detail = None
        else:
            enabled_detail = _completed_detail(enabled_result)
        automatic = (
            True
            if enabled_detail in {"enabled", "enabled-runtime", "linked", "linked-runtime"}
            else False
            if enabled_detail in {"disabled", "masked", "masked-runtime"}
            else None
        )
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
            automatic=automatic,
            registration_valid=registration_valid,
            definition_fingerprint=fingerprint,
            definition_path=str(self.definition_path),
            log_hint=self.log_hint,
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

    @property
    def log_hint(self) -> str:
        log_dir = native.services_data_dir.resolve() / "logs"
        return (
            f"{log_dir / 'scheduler-daemon.log'}, "
            f"{log_dir / 'scheduler.stdout.log'}, or {log_dir / 'scheduler.stderr.log'}"
        )

    def install(self) -> Path:
        return native.install_macos()

    def uninstall(self) -> None:
        native.uninstall_macos()

    def start(self) -> None:
        if not self.definition_path.exists():
            raise RuntimeError("the Taskflows scheduler LaunchAgent is not installed")
        loaded = native._run(["launchctl", "print", self.service_target], check=False)
        if loaded.returncode != 0:
            native._run(["launchctl", "bootstrap", self.domain, str(self.definition_path)])
        native._run(["launchctl", "kickstart", "-k", self.service_target])

    def stop(self) -> None:
        if not self.definition_path.exists():
            raise RuntimeError("the Taskflows scheduler LaunchAgent is not installed")
        native._run(["launchctl", "bootout", self.domain, str(self.definition_path)], check=False)

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
                automatic=False,
                registration_valid=False,
                definition_path=str(self.definition_path),
                log_hint=self.log_hint,
            )
        fingerprint: str | None = None
        registration_valid: bool | None = None
        try:
            with self.definition_path.open("rb") as stream:
                definition = plistlib.load(stream)
            value = definition.get("TaskflowsDefinitionFingerprint")
            fingerprint = value if isinstance(value, str) else None
            registration_valid = fingerprint == native.definition_fingerprint()
        except (OSError, plistlib.InvalidFileException, AttributeError):
            registration_valid = None
        try:
            result = native._run(["launchctl", "print", self.service_target], check=False)
        except (OSError, TimeoutError) as exc:
            return SupervisorStatus(
                backend="launchd",
                installed=True,
                state="unknown",
                automatic=None,
                registration_valid=None,
                definition_path=str(self.definition_path),
                log_hint=self.log_hint,
                detail=str(exc),
            )
        detail = _completed_detail(result)
        state: SupervisorState = "stopped"
        if result.returncode == 0 and detail and "state = running" in detail:
            state = "running"
        exit_match = re.search(r"last exit code\s*=\s*(-?\d+)", detail or "")
        last_exit_code = int(exit_match.group(1)) if exit_match else None
        if state == "stopped" and last_exit_code not in (None, 0):
            state = "failed"
        automatic: bool | None = None
        try:
            disabled = native._run(["launchctl", "print-disabled", self.domain], check=False)
        except (OSError, TimeoutError):
            disabled_detail = ""
        else:
            disabled_detail = _completed_detail(disabled) or ""
            if disabled.returncode == 0:
                # print-disabled lists persistent overrides. An absent label
                # uses launchd's enabled-by-default LaunchAgent behavior.
                automatic = True
        disabled_match = re.search(
            rf'"{re.escape(native.MACOS_LABEL)}"\s*=>\s*(true|false)',
            disabled_detail,
            flags=re.IGNORECASE,
        )
        if disabled_match:
            automatic = disabled_match.group(1).lower() == "false"
        return SupervisorStatus(
            backend="launchd",
            installed=True,
            state=state,
            automatic=automatic,
            registration_valid=registration_valid,
            definition_fingerprint=fingerprint,
            definition_path=str(self.definition_path),
            last_exit_code=last_exit_code,
            log_hint=self.log_hint,
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

    @property
    def log_hint(self) -> str:
        daemon_log = native.services_data_dir.resolve() / "logs" / "scheduler-daemon.log"
        return f"{daemon_log} or Task Scheduler Library > Taskflows > Scheduler > History"

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
                automatic=None,
                registration_valid=None,
                log_hint=self.log_hint,
                detail=str(exc),
            )
        if task is None:
            return SupervisorStatus(
                backend="windows-task-scheduler",
                installed=False,
                state="not-installed",
                automatic=False,
                registration_valid=False,
                log_hint=self.log_hint,
            )
        task_state = int(getattr(task, "State", 0))
        enabled_value = getattr(task, "Enabled", None)
        automatic: bool | None = None
        try:
            triggers = task.Definition.Triggers
            logon_triggers = [
                triggers.Item(index)
                for index in range(1, int(triggers.Count) + 1)
                if int(getattr(triggers.Item(index), "Type", -1)) == native._TASK_TRIGGER_LOGON
            ]
        except Exception:
            logon_triggers = None
        if logon_triggers is not None:
            automatic = bool(enabled_value) and any(
                bool(getattr(trigger, "Enabled", False)) for trigger in logon_triggers
            )
        source = getattr(getattr(task, "Definition", None), "RegistrationInfo", None)
        fingerprint_value = getattr(source, "Source", None)
        fingerprint = fingerprint_value if isinstance(fingerprint_value, str) else None
        registration_valid = fingerprint == native.definition_fingerprint()
        result_value = getattr(task, "LastTaskResult", None)
        last_exit_code = int(result_value) if isinstance(result_value, int) else None
        # TASK_STATE_RUNNING=4, READY=3, QUEUED=2, DISABLED=1, UNKNOWN=0.
        state: SupervisorState = "running" if task_state == 4 else "stopped"
        if task_state == 2:
            state = "starting"
        if task_state == 0:
            state = "unknown"
        # 0x413xx values are Task Scheduler lifecycle statuses (not process
        # failures), including "has not yet run" and "currently running".
        result_failed = (
            last_exit_code != 0 and not 0x41300 <= last_exit_code <= 0x413FF
            if last_exit_code is not None
            else False
        )
        if state == "stopped" and result_failed:
            state = "failed"
        return SupervisorStatus(
            backend="windows-task-scheduler",
            installed=True,
            state=state,
            automatic=automatic,
            registration_valid=registration_valid,
            definition_fingerprint=fingerprint,
            last_exit_code=last_exit_code,
            log_hint=self.log_hint,
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
