import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from dbus_next.errors import DBusError

from taskflows.admin import core
from taskflows.alerts.components import Table
from taskflows.systemd import dbus, units


@pytest.mark.asyncio
async def test_cached_systemd_manager_has_no_per_call_health_round_trip(monkeypatch):
    manager = object()
    monkeypatch.setattr(dbus, "_dbus_manager", manager)
    monkeypatch.setattr(dbus, "_dbus_session_bus", SimpleNamespace(connected=True))
    monkeypatch.setattr(dbus, "_dbus_session_bus_loop_id", id(asyncio.get_running_loop()))

    assert await dbus.systemd_manager() is manager


@pytest.mark.asyncio
async def test_schedule_info_fetches_properties_by_interface(monkeypatch):
    calls: list[str] = []

    class Properties:
        def __init__(self, values):
            self.values = values

        async def call_get_all(self, interface):
            calls.append(interface)
            return self.values

    service_properties = Properties(
        {
            "ActiveEnterTimestamp": SimpleNamespace(value=1_000_000),
            "ActiveExitTimestamp": SimpleNamespace(value=2_000_000),
        }
    )
    timer_properties = Properties(
        {
            "NextElapseUSecRealtime": SimpleNamespace(value=3_000_000),
            "TimersCalendar": SimpleNamespace(value=[]),
            "TimersMonotonic": SimpleNamespace(value=[]),
        }
    )

    class Manager:
        async def call_load_unit(self, name):
            return "/service" if name.endswith(".service") else "/timer"

    class Proxy:
        def __init__(self, properties):
            self.properties = properties

        def get_interface(self, name):
            assert name == "org.freedesktop.DBus.Properties"
            return self.properties

    async def get_proxy(_bus, path):
        return Proxy(service_properties if path == "/service" else timer_properties)

    monkeypatch.setattr(units, "systemd_manager", lambda: asyncio.sleep(0, result=Manager()))
    monkeypatch.setattr(units, "session_dbus", lambda: asyncio.sleep(0, result=object()))
    monkeypatch.setattr(units, "_get_unit_proxy", get_proxy)

    result = await units.get_schedule_info("example")

    assert calls == ["org.freedesktop.systemd1.Unit", "org.freedesktop.systemd1.Timer"]
    assert result["Last Start"] == datetime.fromtimestamp(1, tz=UTC)
    assert result["Last Finish"] == datetime.fromtimestamp(2, tz=UTC)
    assert result["Next Start"] == datetime.fromtimestamp(3, tz=UTC)


@pytest.mark.asyncio
async def test_schedule_info_allows_service_without_timer(monkeypatch):
    class Properties:
        async def call_get_all(self, interface):
            assert interface == "org.freedesktop.systemd1.Unit"
            return {"ActiveEnterTimestamp": SimpleNamespace(value=1_000_000)}

    class Manager:
        async def call_load_unit(self, name):
            if name.endswith(".timer"):
                raise DBusError("org.freedesktop.systemd1.NoSuchUnit", "missing")
            return "/service"

    class Proxy:
        def get_interface(self, name):
            assert name == "org.freedesktop.DBus.Properties"
            return Properties()

    monkeypatch.setattr(units, "systemd_manager", lambda: asyncio.sleep(0, result=Manager()))
    monkeypatch.setattr(units, "session_dbus", lambda: asyncio.sleep(0, result=object()))
    monkeypatch.setattr(units, "_get_unit_proxy", lambda *_: asyncio.sleep(0, result=Proxy()))

    result = await units.get_schedule_info("example")

    assert result["Last Start"] == datetime.fromtimestamp(1, tz=UTC)
    assert result["Next Start"] is None
    assert result["Timers Calendar"] == []


@pytest.mark.asyncio
async def test_schedule_info_preserves_auxiliary_unit_prefix(monkeypatch):
    loaded = []

    class Manager:
        async def call_load_unit(self, name):
            loaded.append(name)
            if name.endswith(".timer"):
                raise DBusError("org.freedesktop.systemd1.NoSuchUnit", "missing")
            return "/service"

    class Properties:
        async def call_get_all(self, _interface):
            return {}

    class Proxy:
        def get_interface(self, _name):
            return Properties()

    monkeypatch.setattr(units, "systemd_manager", lambda: asyncio.sleep(0, result=Manager()))
    monkeypatch.setattr(units, "session_dbus", lambda: asyncio.sleep(0, result=object()))
    monkeypatch.setattr(units, "_get_unit_proxy", lambda *_: asyncio.sleep(0, result=Proxy()))

    await units.get_schedule_info("stop-taskflows-job.service")

    assert loaded == ["stop-taskflows-job.service", "stop-taskflows-job.timer"]


@pytest.mark.asyncio
async def test_status_enriches_units_concurrently(monkeypatch):
    active = 0
    maximum_active = 0
    service_paths = {f"/tmp/taskflows-job-{index}.service": "enabled" for index in range(4)}
    timer_paths = {path.replace(".service", ".timer"): "enabled" for path in service_paths}

    async def file_states(unit_type=None, **_kwargs):
        if unit_type == "service":
            return service_paths
        if unit_type == "timer":
            return timer_paths
        return {**service_paths, **timer_paths}

    async def schedule_info(_unit_name):
        nonlocal active, maximum_active
        active += 1
        maximum_active = max(maximum_active, active)
        await asyncio.sleep(0.01)
        active -= 1
        return {
            "Last Start": None,
            "Last Finish": None,
            "Next Start": None,
            "Timers Calendar": [],
            "Timers Monotonic": [],
        }

    async def runtime_units(**_kwargs):
        return [
            {
                "unit_name": f"taskflows-job-{index}.service",
                "description": "job",
                "load_state": "loaded",
                "active_state": "inactive",
                "sub_state": "dead",
            }
            for index in range(4)
        ]

    monkeypatch.setattr(core, "get_unit_file_states", file_states)
    monkeypatch.setattr(core, "get_schedule_info", schedule_info)
    monkeypatch.setattr(core, "get_units", runtime_units)

    response = await core.status(details=True, as_json=True)

    assert len(response["status"]) == 4
    assert maximum_active > 1


@pytest.mark.asyncio
async def test_default_status_uses_bulk_summary_without_schedule_queries(monkeypatch):
    schedule_queries = 0

    async def file_states(unit_type=None, **_kwargs):
        if unit_type:
            return {f"/tmp/taskflows-job.{unit_type}": "enabled"}
        return {
            "/tmp/taskflows-job.service": "enabled",
            "/tmp/taskflows-job.timer": "enabled",
        }

    async def schedule_info(_unit_name):
        nonlocal schedule_queries
        schedule_queries += 1
        return {}

    async def runtime_units(**_kwargs):
        return []

    monkeypatch.setattr(core, "get_unit_file_states", file_states)
    monkeypatch.setattr(core, "get_schedule_info", schedule_info)
    monkeypatch.setattr(core, "get_units", runtime_units)

    response = await core.status(as_json=True)

    assert schedule_queries == 0
    assert response["status"][0]["load_state"] == "not-loaded"
    assert "Last Start" not in response["status"][0]


@pytest.mark.asyncio
async def test_status_keeps_auxiliary_services_distinct_and_ignores_orphan_timers(monkeypatch):
    async def file_states(**_kwargs):
        return {
            "/tmp/taskflows-job.service": "enabled",
            "/tmp/stop-taskflows-job.service": "enabled",
            "/tmp/restart-taskflows-job.service": "enabled",
            "/tmp/taskflows-stop-legit.service": "enabled",
            "/tmp/taskflows-job.timer": "enabled",
            "/tmp/taskflows-orphan.timer": "enabled",
        }

    async def runtime_units(**_kwargs):
        return [
            {
                "unit_name": name,
                "description": name,
                "load_state": "loaded",
                "active_state": "inactive",
                "sub_state": "dead",
            }
            for name in (
                "taskflows-job.service",
                "stop-taskflows-job.service",
                "restart-taskflows-job.service",
                "taskflows-stop-legit.service",
            )
        ]

    monkeypatch.setattr(core, "get_unit_file_states", file_states)
    monkeypatch.setattr(core, "get_units", runtime_units)

    response = await core.status(all=True, as_json=True)

    assert {row["Service"] for row in response["status"]} == {
        "job",
        "stop-taskflows-job",
        "restart-taskflows-job",
        "stop-legit",
    }

    default_response = await core.status(as_json=True)
    assert {row["Service"] for row in default_response["status"]} == {"job", "stop-legit"}


@pytest.mark.asyncio
async def test_multiple_servers_are_queried_concurrently(monkeypatch):
    active = 0
    maximum_active = 0

    async def list_services(host=None, **_kwargs):
        nonlocal active, maximum_active
        active += 1
        maximum_active = max(maximum_active, active)
        await asyncio.sleep(0.01)
        active -= 1
        return Table([{"Service": host}])

    monkeypatch.setattr(core, "list_services", list_services)

    # Click supplies repeated --server options as a tuple.
    await core.execute_command_on_servers("list", servers=("one", "two", "three"))

    assert maximum_active == 3
