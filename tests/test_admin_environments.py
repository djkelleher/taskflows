from datetime import datetime, timezone

import pytest

from taskflows.admin import environments as envs


def _named_env(name: str, env_type: str = "venv", environment: dict | None = None):
    if environment is None:
        environment = (
            {"env_name": f"{name}-env"}
            if env_type == "venv"
            else {"image": "python:3.12"}
        )
    return envs.NamedEnvironment(
        name=name,
        type=env_type,
        environment=environment,
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


@pytest.fixture
def isolated_environments_file(tmp_path, monkeypatch):
    monkeypatch.setattr(envs, "environments_file", tmp_path / "environments.json")
    return envs.environments_file


def test_corrupt_environment_registry_fails_closed(isolated_environments_file):
    isolated_environments_file.write_text("{not-json")

    with pytest.raises(RuntimeError, match="not valid JSON"):
        envs.load_environments()


def test_non_object_environment_registry_fails_closed(isolated_environments_file):
    isolated_environments_file.write_text("[]")

    with pytest.raises(RuntimeError, match="must contain a JSON object"):
        envs.load_environments()


def test_environment_registry_validates_loaded_payload(isolated_environments_file):
    isolated_environments_file.write_text(
        '{"bad": {"name": "bad", "type": "venv", "environment": {}}}'
    )

    with pytest.raises(ValueError, match="env_name is required"):
        envs.load_environments()


def test_environment_registry_rejects_key_payload_name_mismatch(
    isolated_environments_file,
):
    isolated_environments_file.write_text(
        '{"stored": {"name": "payload", "type": "venv", '
        '"environment": {"env_name": "venv"}}}'
    )

    with pytest.raises(RuntimeError, match="does not match payload name"):
        envs.load_environments()


def test_update_environment_validates_payload(isolated_environments_file):
    envs.create_environment(_named_env("base"))

    with pytest.raises(ValueError, match="env_name is required"):
        envs.update_environment(
            "base",
            _named_env("base", environment={}),
        )


def test_update_environment_rename_cannot_overwrite_existing_name(
    isolated_environments_file,
):
    envs.create_environment(_named_env("base"))
    envs.create_environment(_named_env("existing"))

    with pytest.raises(ValueError, match="already exists"):
        envs.update_environment("base", _named_env("existing"))


@pytest.mark.parametrize(
    "name",
    ["", " ", ".hidden", "-env", "env.", "env-", "../env", "env/name", r"env\name"],
)
def test_create_environment_validates_name(isolated_environments_file, name):
    with pytest.raises((TypeError, ValueError)):
        envs.create_environment(_named_env(name))


def test_update_environment_validates_new_name(isolated_environments_file):
    envs.create_environment(_named_env("base"))

    with pytest.raises(ValueError, match="Environment names"):
        envs.update_environment("base", _named_env(".hidden"))


def test_deserialize_environment_rejects_unknown_type():
    with pytest.raises(ValueError, match="Unknown environment type"):
        envs._deserialize_environment({}, "unknown")
