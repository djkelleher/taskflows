from unittest.mock import AsyncMock

import pytest

from taskflows.admin import core
from taskflows.dashboard import Dashboard
from taskflows.service import Service, ServiceRegistry


def test_deduplicate_services_keeps_last_definition_in_original_order():
    first_web = Service(name="web", start_command="python old.py")
    worker = Service(name="worker", start_command="python worker.py")
    second_web = Service(name="web", start_command="python new.py")

    services = core._deduplicate_services([first_web, worker, second_web])

    assert services == [second_web, worker]


@pytest.mark.asyncio
async def test_create_skips_duplicate_service_names(monkeypatch):
    standalone = Service(name="web", start_command="python old.py")
    worker = Service(name="worker", start_command="python worker.py")
    registry_web = Service(name="web", start_command="python new.py")
    registry = ServiceRegistry(registry_web)
    created = []

    def find_instances(class_type, search_in):
        if class_type is Service:
            return [standalone, worker]
        if class_type is ServiceRegistry:
            return [registry]
        if class_type is Dashboard:
            return []
        return []

    async def fake_create(self, defer_reload=False):
        created.append((self.name, self.start_command, defer_reload))

    monkeypatch.setattr(core, "find_instances", find_instances)
    monkeypatch.setattr(Service, "create", fake_create)
    monkeypatch.setattr(core, "reload_unit_files", AsyncMock())

    result = await core.create(search_in=".", as_json=True)

    assert created == [
        ("web", "python new.py", True),
        ("worker", "python worker.py", True),
    ]
    assert result["services"] == ["web", "worker"]
