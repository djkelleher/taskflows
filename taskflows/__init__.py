"""taskflows: tasks and systemd services with scheduling, constraints, and alerts.

Submodules are imported lazily (PEP 562): `import taskflows` performs no
filesystem writes and does not pull in optional dependency stacks. Grafana
dashboard types live in `taskflows.dashboard` (requires the `grafana` extra).
"""

from typing import TYPE_CHECKING

_SYMBOL_MODULES = {
    # tasks
    "Alerts": "tasks",
    "get_current_task_id": "tasks",
    "run_task": "tasks",
    "task": "tasks",
    # services
    "RestartPolicy": "service",
    "Service": "service",
    "ServiceRegistry": "service",
    "Venv": "service",
    # schedules
    "Calendar": "schedule",
    "Periodic": "schedule",
    # docker environments
    "ContainerLimits": "docker",
    "DockerContainer": "docker",
    "DockerImage": "docker",
    "Ulimit": "docker",
    "Volume": "docker",
    # resource constraints
    "CPUPressure": "constraints",
    "CPUs": "constraints",
    "CgroupConfig": "constraints",
    "HardwareConstraint": "constraints",
    "IOPressure": "constraints",
    "Memory": "constraints",
    "MemoryPressure": "constraints",
    "SystemLoadConstraint": "constraints",
    # entrypoints
    "async_entrypoint": "entrypoints",
    "get_shutdown_handler": "entrypoints",
    # YAML round-tripping
    "load_services_from_yaml": "serialization",
    "save_services_to_yaml": "serialization",
}

__all__ = sorted(_SYMBOL_MODULES)


def __getattr__(name: str):
    module_name = _SYMBOL_MODULES.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    from importlib import import_module

    value = getattr(import_module(f".{module_name}", __name__), name)
    globals()[name] = value
    return value


def __dir__():
    return sorted(set(globals()) | set(__all__))


if TYPE_CHECKING:
    from .constraints import (
        CgroupConfig,
        CPUPressure,
        CPUs,
        HardwareConstraint,
        IOPressure,
        Memory,
        MemoryPressure,
        SystemLoadConstraint,
    )
    from .docker import ContainerLimits, DockerContainer, DockerImage, Ulimit, Volume
    from .entrypoints import async_entrypoint, get_shutdown_handler
    from .schedule import Calendar, Periodic
    from .serialization import load_services_from_yaml, save_services_to_yaml
    from .service import RestartPolicy, Service, ServiceRegistry, Venv
    from .tasks import Alerts, get_current_task_id, run_task, task
