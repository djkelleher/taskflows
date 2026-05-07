import pytest

from taskflows import db


@pytest.fixture
def isolated_servers_file(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "_servers_file", tmp_path / "servers.json")
    return db._servers_file


def test_upsert_server_validates_hostname(isolated_servers_file):
    with pytest.raises(ValueError, match="hostname"):
        db.upsert_server("", "203.0.113.10")


@pytest.mark.parametrize("hostname", [" host-a", "host-a ", "\thost-a"])
def test_upsert_server_rejects_hostname_boundary_whitespace(
    isolated_servers_file, hostname
):
    with pytest.raises(ValueError, match="whitespace"):
        db.upsert_server(hostname, "203.0.113.10")


@pytest.mark.parametrize("public_ipv4", ["not-an-ip", "2001:db8::1"])
def test_upsert_server_validates_public_ipv4(isolated_servers_file, public_ipv4):
    with pytest.raises(ValueError, match="public_ipv4"):
        db.upsert_server("host-a", public_ipv4)


def test_get_servers_rejects_malformed_records(isolated_servers_file):
    isolated_servers_file.write_text('{"host-a": {"public_ipv4": "203.0.113.10"}}')

    with pytest.raises(RuntimeError, match="public_ipv4 and last_updated"):
        db.get_servers()


def test_server_registry_round_trip(isolated_servers_file):
    db.upsert_server("host-a", "203.0.113.10")

    servers = db.get_servers()

    assert servers == [
        {
            "hostname": "host-a",
            "public_ipv4": "203.0.113.10",
            "last_updated": servers[0]["last_updated"],
        }
    ]
    assert db.remove_server("host-a") is True
    assert db.remove_server("host-a") is False
