from unittest.mock import Mock

import requests
import pytest

from taskflows.admin.core import _API_RESPONSE_MAX_CHARS, call_api, task_history
from taskflows.admin import utils


def test_get_public_ipv4_skips_invalid_responses(monkeypatch):
    utils.get_public_ipv4.cache_clear()
    responses = iter(
        [
            Mock(status_code=200, text="not-an-ip"),
            Mock(status_code=200, text="2001:db8::1"),
            Mock(status_code=200, text="203.0.113.10\n"),
        ]
    )

    monkeypatch.setattr(utils.requests, "get", lambda *_, **__: next(responses))

    try:
        assert utils.get_public_ipv4() == "203.0.113.10"
    finally:
        utils.get_public_ipv4.cache_clear()


def test_get_public_ipv4_skips_empty_responses(monkeypatch):
    utils.get_public_ipv4.cache_clear()
    responses = iter(
        [
            Mock(status_code=200, text=" \n"),
            Mock(status_code=200, text="203.0.113.10\n"),
        ]
    )

    monkeypatch.setattr(utils.requests, "get", lambda *_, **__: next(responses))

    try:
        assert utils.get_public_ipv4() == "203.0.113.10"
    finally:
        utils.get_public_ipv4.cache_clear()


def test_call_api_returns_dict_for_long_non_json_http_error(monkeypatch):
    response = Mock(
        status_code=500,
        text="x" * (_API_RESPONSE_MAX_CHARS + 20),
    )
    response.json.side_effect = ValueError("not json")
    response.raise_for_status.side_effect = requests.HTTPError("server error")

    monkeypatch.setattr(
        "taskflows.admin.core.requests.request",
        Mock(return_value=response),
    )

    result = call_api("localhost:7777", "/health")

    assert result["status_code"] == 500
    assert result["endpoint"] == "/health"
    assert "response_body" in result
    assert "truncated 20 chars" in result["response_body"]


@pytest.mark.asyncio
async def test_task_history_escapes_example_logql_match():
    result = await task_history(match='worker.*"prod\\job', as_json=True)

    assert r'{service_name=~".*worker\\.\\*\"prod\\\\job.*"}' in result["message"]
