#!/usr/bin/env python3
"""Comprehensive test suite for API authentication on all endpoints."""

import json
import pytest
import time
import unittest
from types import SimpleNamespace
from typing import Dict
from urllib.parse import urlsplit
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from taskflows.admin.api import (
    MAX_CREATE_YAML_BYTES,
    _validate_declared_create_request_size,
    app,
    unhandled_exception_handler,
)
from taskflows.admin.security import (
    SecurityConfig,
    calculate_hmac_signature,
    create_hmac_headers,
    generate_hmac_secret,
)


class TestAPIAuthentication(unittest.TestCase):
    """Test HMAC authentication for all API endpoints."""

    @classmethod
    def setUpClass(cls):
        """Set up test client and mock security config."""
        cls.client = TestClient(app)
        cls.hmac_secret = generate_hmac_secret()

        # Mock security config
        cls.mock_security_config = SecurityConfig(
            enable_hmac=True,
            hmac_secret=cls.hmac_secret,
            hmac_header="X-HMAC-Signature",
            hmac_timestamp_header="X-Timestamp",
            hmac_window_seconds=300,
            enable_cors=True,
            enable_security_headers=True,
            log_security_events=True,
        )

        # Patch the security config
        cls.patcher = patch(
            "taskflows.admin.api.security_config", cls.mock_security_config
        )
        cls.patcher.start()

    @classmethod
    def tearDownClass(cls):
        """Clean up patches."""
        cls.patcher.stop()

    def generate_hmac_headers(
        self, body: str = "", method: str = "GET", endpoint: str = "/list"
    ) -> Dict[str, str]:
        """Generate valid HMAC headers for a request."""
        parsed = urlsplit(endpoint)
        return create_hmac_headers(
            self.hmac_secret,
            body,
            method=method,
            path=parsed.path,
            query_string=parsed.query,
        )

    def test_health_endpoint_no_auth(self):
        """Test that /health endpoint doesn't require authentication."""
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "ok")
        self.assertIn("hostname", data)

    def test_endpoints_without_auth_fail(self):
        """Test that all protected endpoints fail without authentication."""
        endpoints = [
            ("GET", "/list-servers"),
            ("GET", "/metrics"),
            ("GET", "/history"),
            ("GET", "/list"),
            ("GET", "/status"),
            ("GET", "/logs/test-service"),
            ("POST", "/create", {"yaml_content": "services: []"}),
            ("POST", "/start", {"match": "test"}),
            ("POST", "/stop", {"match": "test"}),
            ("POST", "/restart", {"match": "test"}),
            ("POST", "/enable", {"match": "test"}),
            ("POST", "/disable", {"match": "test"}),
            ("POST", "/remove", {"match": "test"}),
            ("GET", "/show/test"),
        ]

        for method, endpoint, *body in endpoints:
            with self.subTest(endpoint=endpoint):
                if method == "GET":
                    response = self.client.get(endpoint)
                elif method == "POST":
                    response = self.client.post(endpoint, json=body[0] if body else {})

                self.assertEqual(
                    response.status_code,
                    401,
                    f"Endpoint {endpoint} should require auth",
                )
                self.assertIn("HMAC signature", response.json()["detail"])

    def test_endpoints_with_valid_auth_succeed(self):
        """Test that all endpoints work with valid authentication."""
        # Mock necessary dependencies - patch where used (api module), not where defined
        with patch(
            "taskflows.admin.api.list_servers", new_callable=AsyncMock, return_value=[]
        ):
            with patch(
                "taskflows.admin.api.list_services",
                new_callable=AsyncMock,
                return_value={"services": [], "hostname": "test"},
            ):
                with patch(
                    "taskflows.admin.api.service_status",
                    new_callable=AsyncMock,
                    return_value={"services": [], "hostname": "test"},
                ):
                    with patch(
                        "taskflows.admin.api.task_history",
                        new_callable=AsyncMock,
                        return_value={"history": [], "hostname": "test"},
                    ):
                        with patch(
                            "taskflows.admin.api.logs",
                            new_callable=AsyncMock,
                            return_value={"logs": "", "hostname": "test"},
                        ):
                            with patch(
                                "taskflows.admin.api.create",
                                new_callable=AsyncMock,
                                return_value={"created": [], "hostname": "test"},
                            ):
                                with patch(
                                    "taskflows.admin.api.start",
                                    new_callable=AsyncMock,
                                    return_value={"started": [], "hostname": "test"},
                                ):
                                    with patch(
                                        "taskflows.admin.api.stop",
                                        new_callable=AsyncMock,
                                        return_value={
                                            "stopped": [],
                                            "hostname": "test",
                                        },
                                    ):
                                        with patch(
                                            "taskflows.admin.api.restart",
                                            new_callable=AsyncMock,
                                            return_value={
                                                "restarted": [],
                                                "hostname": "test",
                                            },
                                        ):
                                            with patch(
                                                "taskflows.admin.api.enable",
                                                new_callable=AsyncMock,
                                                return_value={
                                                    "enabled": [],
                                                    "hostname": "test",
                                                },
                                            ):
                                                with patch(
                                                    "taskflows.admin.api.disable",
                                                    new_callable=AsyncMock,
                                                    return_value={
                                                        "disabled": [],
                                                        "hostname": "test",
                                                    },
                                                ):
                                                    with patch(
                                                        "taskflows.admin.api.remove",
                                                        new_callable=AsyncMock,
                                                        return_value={
                                                            "removed": [],
                                                            "hostname": "test",
                                                        },
                                                    ):
                                                        with patch(
                                                            "taskflows.admin.api.show",
                                                            new_callable=AsyncMock,
                                                            return_value={
                                                                "files": [],
                                                                "hostname": "test",
                                                            },
                                                        ):
                                                            self._test_all_endpoints_with_auth()

    def _test_all_endpoints_with_auth(self):
        """Helper to test all endpoints with valid auth."""
        test_cases = [
            ("GET", "/list-servers", None, 200),
            ("GET", "/metrics", None, 200),
            ("GET", "/history?limit=1", None, 200),
            ("GET", "/list", None, 200),
            ("GET", "/status", None, 200),
            ("GET", "/logs/test-service", None, 200),
            ("POST", "/create", {"yaml_content": "services: []"}, 200),
            ("POST", "/start", {"match": "test"}, 200),
            ("POST", "/stop", {"match": "test"}, 200),
            ("POST", "/restart", {"match": "test"}, 200),
            ("POST", "/enable", {"match": "test"}, 200),
            ("POST", "/disable", {"match": "test"}, 200),
            ("POST", "/remove", {"match": "test"}, 200),
            ("GET", "/show/test", None, 200),
        ]

        for method, endpoint, body, expected_status in test_cases:
            with self.subTest(endpoint=endpoint):
                body_str = json.dumps(body) if body else ""
                headers = self.generate_hmac_headers(body_str, method, endpoint)

                if body:
                    headers["Content-Type"] = "application/json"

                if method == "GET":
                    response = self.client.get(endpoint, headers=headers)
                elif method == "POST":
                    response = self.client.post(
                        endpoint, data=body_str, headers=headers
                    )

                self.assertEqual(
                    response.status_code,
                    expected_status,
                    f"Endpoint {endpoint} failed with auth: {response.text}",
                )

    def test_invalid_hmac_signature_fails(self):
        """Test that invalid HMAC signatures are rejected."""
        headers = {
            "X-HMAC-Signature": "invalid_signature",
            "X-Timestamp": str(int(time.time())),
            "X-Nonce": "nonce-invalid-signature",
        }
        response = self.client.get("/list", headers=headers)
        self.assertEqual(response.status_code, 401)
        self.assertIn("Invalid HMAC signature", response.json()["detail"])

    def test_create_rejects_oversized_yaml(self):
        """Oversized service definitions should be rejected before processing."""
        body = json.dumps({"yaml_content": "x" * (MAX_CREATE_YAML_BYTES + 1)})
        headers = self.generate_hmac_headers(body, "POST", "/create")
        headers["Content-Type"] = "application/json"

        response = self.client.post("/create", data=body, headers=headers)

        self.assertEqual(response.status_code, 413)
        self.assertIn("too large", response.json()["detail"])

    def test_create_requires_declared_content_length(self):
        """Create requests without a declared size are rejected before body reads."""
        request = SimpleNamespace(
            url=SimpleNamespace(path="/create"),
            headers={},
        )

        response = _validate_declared_create_request_size(request)

        self.assertIsNotNone(response)
        self.assertEqual(response.status_code, 411)

    def test_expired_timestamp_fails(self):
        """Test that expired timestamps are rejected."""
        old_timestamp = str(int(time.time()) - 600)  # 10 minutes old
        nonce = "nonce-expired"
        signature = calculate_hmac_signature(
            self.hmac_secret,
            old_timestamp,
            method="GET",
            path="/list",
            nonce=nonce,
        )
        headers = {
            "X-HMAC-Signature": signature,
            "X-Timestamp": old_timestamp,
            "X-Nonce": nonce,
        }
        response = self.client.get("/list", headers=headers)
        self.assertEqual(response.status_code, 401)
        self.assertIn("Request timestamp expired", response.json()["detail"])

    def test_missing_timestamp_fails(self):
        """Test that missing timestamp is rejected."""
        headers = {
            "X-HMAC-Signature": "some_signature",
        }
        response = self.client.get("/list", headers=headers)
        self.assertEqual(response.status_code, 401)
        self.assertIn("HMAC signature", response.json()["detail"])

    def test_missing_signature_fails(self):
        """Test that missing signature is rejected."""
        headers = {
            "X-Timestamp": str(int(time.time())),
        }
        response = self.client.get("/list", headers=headers)
        self.assertEqual(response.status_code, 401)
        self.assertIn("HMAC signature", response.json()["detail"])

    def test_body_tampering_detected(self):
        """Test that body tampering is detected via HMAC."""
        original_body = {"match": "test"}
        body_str = json.dumps(original_body)
        headers = self.generate_hmac_headers(body_str, "POST", "/start")
        headers["Content-Type"] = "application/json"

        # Send different body than what was signed
        tampered_body = {"match": "tampered"}
        tampered_str = json.dumps(tampered_body)

        response = self.client.post("/start", data=tampered_str, headers=headers)
        self.assertEqual(response.status_code, 401)
        self.assertIn("Invalid HMAC signature", response.json()["detail"])

    def test_path_tampering_detected(self):
        """Test that a signature for one path cannot be replayed on another."""
        headers = self.generate_hmac_headers(method="GET", endpoint="/list")
        response = self.client.get("/status", headers=headers)
        self.assertEqual(response.status_code, 401)
        self.assertIn("Invalid HMAC signature", response.json()["detail"])

    def test_nonce_replay_detected(self):
        """Test that a valid HMAC request cannot be replayed with the same nonce."""
        headers = self.generate_hmac_headers(method="GET", endpoint="/list")
        with patch(
            "taskflows.admin.api.list_services",
            new_callable=AsyncMock,
            return_value={"services": [], "hostname": "test"},
        ):
            first = self.client.get("/list", headers=headers)
            second = self.client.get("/list", headers=headers)

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 401)
        self.assertIn("nonce already used", second.json()["detail"])

    def test_query_params_vs_body_params(self):
        """Test endpoints that accept both query and body parameters."""
        # Test with query parameters (should fail without auth)
        response = self.client.post("/start?match=test")
        self.assertEqual(response.status_code, 401)

        # Test with body parameters and auth
        body = {"match": "test"}
        body_str = json.dumps(body)
        headers = self.generate_hmac_headers(body_str, "POST", "/start")
        headers["Content-Type"] = "application/json"

        with patch(
            "taskflows.admin.core.get_unit_files",
            new_callable=AsyncMock,
            return_value=[],
        ):
            with patch("taskflows.admin.core._start_service", new_callable=AsyncMock):
                response = self.client.post("/start", data=body_str, headers=headers)
                self.assertEqual(response.status_code, 200)

    def test_security_headers_present(self):
        """Test that security headers are added to responses."""
        headers = self.generate_hmac_headers(method="GET", endpoint="/list")

        with patch(
            "taskflows.admin.api.list_services",
            new_callable=AsyncMock,
            return_value={"services": [], "hostname": "test"},
        ):
            response = self.client.get("/list", headers=headers)

        expected_headers = {
            "X-Content-Type-Options": "nosniff",
            "X-Frame-Options": "DENY",
            "X-XSS-Protection": "1; mode=block",
            "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
            "Content-Security-Policy": "default-src 'self'",
        }

        for header, value in expected_headers.items():
            self.assertEqual(
                response.headers.get(header),
                value,
                f"Security header {header} not set correctly",
            )


@pytest.mark.asyncio
async def test_unhandled_exception_handler_hides_details_by_default(monkeypatch):
    monkeypatch.delenv("DEBUG", raising=False)
    request = SimpleNamespace(
        method="GET",
        url=SimpleNamespace(path="/boom"),
    )

    response = await unhandled_exception_handler(request, RuntimeError("secret detail"))
    payload = json.loads(response.body)

    assert response.status_code == 500
    assert payload["detail"] == "Internal server error"
    assert payload["path"] == "/boom"
    assert "secret detail" not in response.body.decode()
    assert "error_type" not in payload
    assert "traceback" not in payload


@pytest.mark.asyncio
async def test_unhandled_exception_handler_includes_details_in_debug(monkeypatch):
    monkeypatch.setenv("DEBUG", "true")
    request = SimpleNamespace(
        method="GET",
        url=SimpleNamespace(path="/boom"),
    )

    response = await unhandled_exception_handler(request, RuntimeError("debug detail"))
    payload = json.loads(response.body)

    assert response.status_code == 500
    assert payload["detail"] == "debug detail"
    assert payload["error_type"] == "RuntimeError"
    assert "traceback" in payload


if __name__ == "__main__":
    unittest.main()
