#!/usr/bin/env python3
"""Test HMAC authentication for Services API."""

import hashlib
import hmac
import json
import time
from pathlib import Path

import requests


def test_hmac_auth():
    """Test HMAC authentication with the API."""

    # Load security config
    security_config_file = Path.home() / ".taskflows" / "security.json"

    if not security_config_file.exists():
        print("❌ Security config not found. Run 'tf api security setup' first.")
        return

    with open(security_config_file) as f:
        security_config = json.load(f)

    if not security_config.get("enable_hmac") or not security_config.get("hmac_secret"):
        print("❌ HMAC not enabled. Run 'tf api security setup' first.")
        return

    hmac_secret = security_config["hmac_secret"]
    base_url = "http://localhost:7777"

    print(f"🔐 Testing HMAC authentication with secret: {hmac_secret[:10]}...")

    # Test 1: GET request (no body)
    print("\n📋 Test 1: GET /health")
    timestamp = str(int(time.time()))
    message = f"{timestamp}:"
    signature = hmac.new(hmac_secret.encode(), message.encode(), hashlib.sha256).hexdigest()

    headers = {"X-HMAC-Signature": signature, "X-Timestamp": timestamp}

    try:
        response = requests.get(f"{base_url}/health", headers=headers)
        if response.status_code == 200:
            print("✅ GET request successful:", response.json())
        else:
            print("❌ GET request failed:", response.status_code, response.text)
    except Exception as e:
        print("❌ GET request error:", str(e))

    # Test 2: POST request with body
    print("\n📋 Test 2: POST /list")
    timestamp = str(int(time.time()))
    body = json.dumps({"match": "test"}, separators=(",", ":"))
    message = f"{timestamp}:{body}"
    signature = hmac.new(hmac_secret.encode(), message.encode(), hashlib.sha256).hexdigest()

    headers = {
        "X-HMAC-Signature": signature,
        "X-Timestamp": timestamp,
        "Content-Type": "application/json",
    }

    try:
        response = requests.post(f"{base_url}/list", data=body, headers=headers)
        if response.status_code == 200:
            print("✅ POST request successful")
        else:
            print("❌ POST request failed:", response.status_code, response.text)
    except Exception as e:
        print("❌ POST request error:", str(e))

    # Test 3: Request without HMAC
    print("\n📋 Test 3: Request without HMAC headers")
    try:
        response = requests.get(f"{base_url}/health")
        if response.status_code == 401:
            print("✅ Correctly rejected request without HMAC")
        else:
            print("❌ Request without HMAC was not rejected:", response.status_code)
    except Exception as e:
        print("❌ Request error:", str(e))

    # Test 4: Request with expired timestamp
    print("\n📋 Test 4: Request with expired timestamp")
    old_timestamp = str(int(time.time()) - 600)  # 10 minutes old
    message = f"{old_timestamp}:"
    signature = hmac.new(hmac_secret.encode(), message.encode(), hashlib.sha256).hexdigest()

    headers = {"X-HMAC-Signature": signature, "X-Timestamp": old_timestamp}

    try:
        response = requests.get(f"{base_url}/health", headers=headers)
        if response.status_code == 401:
            print("✅ Correctly rejected expired timestamp")
        else:
            print("❌ Expired timestamp was not rejected:", response.status_code)
    except Exception as e:
        print("❌ Request error:", str(e))

    print("\n✅ HMAC authentication tests completed!")


if __name__ == "__main__":
    test_hmac_auth()
