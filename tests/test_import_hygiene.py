"""Importing taskflows must be side-effect free.

Guards Phase 4 of the package overhaul: no filesystem writes, no env-var
mutation, no submodule loading, and no Prometheus collector registration at
import time.
"""

import json
import subprocess
import sys

CHECK_SCRIPT = """
import json
import os
import sys

env_before = dict(os.environ)

import taskflows

result = {
    "loaded_submodules": sorted(
        name for name in sys.modules if name.startswith("taskflows.")
    ),
    "heavy_modules": sorted(
        name for name in ("docker", "fastapi", "grafanalib", "structlog", "prometheus_client")
        if name in sys.modules
    ),
    "env_changed": {
        k: os.environ.get(k)
        for k in set(env_before) ^ set(os.environ)
    },
    "home_contents": sorted(os.listdir(os.environ["HOME"])),
}

# Touching a public symbol loads only the module it lives in
taskflows.Service
result["submodules_after_service"] = sorted(
    name for name in sys.modules if name.startswith("taskflows.")
)
result["home_contents_after"] = sorted(os.listdir(os.environ["HOME"]))
print(json.dumps(result))
"""


def run_import_check(tmp_path):
    env = {
        "HOME": str(tmp_path),
        "PATH": "/usr/bin:/bin",
    }
    proc = subprocess.run(
        [sys.executable, "-c", CHECK_SCRIPT],
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def test_import_has_no_side_effects(tmp_path):
    result = run_import_check(tmp_path)

    assert result["home_contents"] == [], "import taskflows must not write to HOME"
    assert result["env_changed"] == {}, "import taskflows must not mutate os.environ"
    assert result["loaded_submodules"] == [], "import taskflows must not load submodules eagerly"
    assert "prometheus_client" not in result["heavy_modules"], (
        "import taskflows must not register Prometheus collectors"
    )
    assert "fastapi" not in result["heavy_modules"]
    assert "grafanalib" not in result["heavy_modules"]


def test_lazy_attribute_access(tmp_path):
    result = run_import_check(tmp_path)

    assert "taskflows.service" in result["submodules_after_service"]
    # accessing Service must still not write anything to HOME
    assert result["home_contents_after"] == []


def test_public_api_symbols_resolve():
    import taskflows

    for name in taskflows.__all__:
        assert getattr(taskflows, name) is not None


def test_metrics_factory_is_idempotent():
    from taskflows.metrics import get_metrics

    first = get_metrics()
    second = get_metrics()
    assert first is second
