import stat

from taskflows import exec as task_exec


def test_get_hmac_secret_replaces_short_secret(tmp_path, monkeypatch):
    monkeypatch.setattr(task_exec, "services_data_dir", tmp_path)
    secret_file = tmp_path / ".pickle_secret"
    secret_file.write_bytes(b"short")
    secret_file.chmod(stat.S_IRUSR | stat.S_IWUSR)

    secret = task_exec._get_hmac_secret()

    assert len(secret) >= 32
    assert secret_file.read_bytes() == secret
    assert secret != b"short"
