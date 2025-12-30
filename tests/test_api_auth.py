#!/usr/bin/env python3
"""Comprehensive test suite for API authentication on all endpoints."""

import json
import time
import unittest
from pathlib import Path
from typing import Dict, Optional, Tuple
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from taskflows.admin.api import app
from taskflows.admin.security import (
    SecurityConfig,
    calculate_hmac_signature,
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

    def generate_hmac_headers(self, body: str = "") -> Dict[str, str]:
        """Generate valid HMAC headers for a request."""
        timestamp = str(int(time.time()))
        signature = calculate_hmac_signature(self.hmac_secret, timestamp, body)
        return {
            "X-HMAC-Signature": signature,
            "X-Timestamp": timestamp,
        }

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
            ("POST", "/register-server", {"address": "test"}),
            ("DELETE", "/remove-server", {"address_or_alias": "test"}),
            ("GET", "/history"),
            ("GET", "/list"),
            ("GET", "/status"),
            ("GET", "/logs/test-service"),
            ("POST", "/create", {"search_in": "/test"}),
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
                elif method == "DELETE":
                    response = self.client.delete(
                        endpoint, json=body[0] if body else {}
                    )

                self.assertEqual(
                    response.status_code,
                    401,
                    f"Endpoint {endpoint} should require auth",
                )
                self.assertIn(
                    "HMAC signature and timestamp required", response.json()["detail"]
                )

    def test_endpoints_with_valid_auth_succeed(self):
        """Test that all endpoints work with valid authentication."""
        # Mock necessary dependencies
        with patch("taskflows.admin.api.list_servers", return_value=[]):
            with patch("taskflows.admin.api.register_server"):
                with patch("taskflows.admin.api.remove_server"):
                    with patch(
                        "taskflows.admin.api.get_unit_files", return_value=[]
                    ):
                        with patch(
                            "taskflows.admin.api.get_unit_file_states",
                            return_value={},
                        ):
                            with patch(
                                "taskflows.admin.api.find_instances",
                                return_value=[],
                            ):
                                with patch(
                                    "taskflows.admin.api.reload_unit_files"
                                ):
                                    with patch(
                                        "taskflows.admin.api._start_service"
                                    ):
                                        with patch(
                                            "taskflows.admin.api._stop_service"
                                        ):
                                            with patch(
                                                "taskflows.admin.api._restart_service"
                                            ):
                                                with patch(
                                                    "taskflows.admin.api._enable_service"
                                                ):
                                                    with patch(
                                                        "taskflows.admin.api._disable_service"
                                                    ):
                                                        with patch(
                                                            "taskflows.admin.api._remove_service",
                                                            return_value=0,
                                                        ):
                                                            self._test_all_endpoints_with_auth()

    def _test_all_endpoints_with_auth(self):
        """Helper to test all endpoints with valid auth."""
        test_cases = [
            ("GET", "/list-servers", None, 200),
            ("POST", "/register-server", {"address": "http://test:8000"}, 200),
            ("DELETE", "/remove-server", {"address_or_alias": "test"}, 200),
            ("GET", "/history?limit=1", None, 200),
            ("GET", "/list", None, 200),
            ("GET", "/status", None, 200),
            ("GET", "/logs/test-service", None, 200),
            ("POST", "/create", {"search_in": "/test"}, 200),
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
                headers = self.generate_hmac_headers(body_str)

                if body:
                    headers["Content-Type"] = "application/json"

                if method == "GET":
                    response = self.client.get(endpoint, headers=headers)
                elif method == "POST":
                    response = self.client.post(
                        endpoint, data=body_str, headers=headers
                    )
                elif method == "DELETE":
                    response = self.client.delete(
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
        }
        response = self.client.get("/list", headers=headers)
        self.assertEqual(response.status_code, 401)
        self.assertIn("Invalid HMAC signature", response.json()["detail"])

    def test_expired_timestamp_fails(self):
        """Test that expired timestamps are rejected."""
        old_timestamp = str(int(time.time()) - 600)  # 10 minutes old
        signature = calculate_hmac_signature(self.hmac_secret, old_timestamp)
        headers = {
            "X-HMAC-Signature": signature,
            "X-Timestamp": old_timestamp,
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
        self.assertIn(
            "HMAC signature and timestamp required", response.json()["detail"]
        )

    def test_missing_signature_fails(self):
        """Test that missing signature is rejected."""
        headers = {
            "X-Timestamp": str(int(time.time())),
        }
        response = self.client.get("/list", headers=headers)
        self.assertEqual(response.status_code, 401)
        self.assertIn(
            "HMAC signature and timestamp required", response.json()["detail"]
        )

    def test_body_tampering_detected(self):
        """Test that body tampering is detected via HMAC."""
        original_body = {"match": "test"}
        body_str = json.dumps(original_body)
        headers = self.generate_hmac_headers(body_str)
        headers["Content-Type"] = "application/json"

        # Send different body than what was signed
        tampered_body = {"match": "tampered"}
        tampered_str = json.dumps(tampered_body)

        response = self.client.post("/start", data=tampered_str, headers=headers)
        self.assertEqual(response.status_code, 401)
        self.assertIn("Invalid HMAC signature", response.json()["detail"])

    def test_query_params_vs_body_params(self):
        """Test endpoints that accept both query and body parameters."""
        # Test with query parameters (should fail without auth)
        response = self.client.post("/start?match=test")
        self.assertEqual(response.status_code, 401)

        # Test with body parameters and auth
        body = {"match": "test"}
        body_str = json.dumps(body)
        headers = self.generate_hmac_headers(body_str)
        headers["Content-Type"] = "application/json"

        with patch("taskflows.admin.api.get_unit_files", return_value=[]):
            with patch("taskflows.admin.api._start_service"):
                response = self.client.post("/start", data=body_str, headers=headers)
                self.assertEqual(response.status_code, 200)

    def test_security_headers_present(self):
        """Test that security headers are added to responses."""
        headers = self.generate_hmac_headers()
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


if __name__ == "__main__":
    unittest.main()
    unittest.main()
