import hashlib
import hmac
import json
import secrets
import time
from typing import List, Optional

from pydantic import BaseModel
from taskflows.common import services_data_dir


# Security configuration
class SecurityConfig(BaseModel):
    """Security configuration for the Services API."""

    # HMAC authentication
    enable_hmac: bool = True
    hmac_secret: str = ""
    hmac_header: str = "X-HMAC-Signature"
    hmac_timestamp_header: str = "X-Timestamp"
    hmac_window_seconds: int = 300  # 5 minutes

    # JWT authentication (for web UI)
    enable_jwt: bool = False
    jwt_secret: str = ""

    # CORS (enabled when UI is enabled)
    enable_cors: bool = False
    allowed_origins: List[str] = ["http://localhost:3000", "http://localhost:7777"]
    allowed_methods: List[str] = ["GET", "POST", "PUT", "DELETE"]
    allowed_headers: List[str] = ["*"]

    # Additional security headers
    enable_security_headers: bool = True

    # Logging
    log_security_events: bool = True


config_file = services_data_dir / "security.json"


def load_security_config() -> SecurityConfig:
    """Load security configuration from file."""
    if config_file.exists():
        return SecurityConfig(**json.loads(config_file.read_text()))
    return SecurityConfig()


security_config = load_security_config()


def save_security_config(config: SecurityConfig):
    """Save security configuration to file."""
    config_file.parent.mkdir(parents=True, exist_ok=True)
    config_file.write_text(json.dumps(config.model_dump()))


def generate_hmac_secret() -> str:
    """Generate a secure HMAC secret."""
    return secrets.token_urlsafe(32)


def calculate_hmac_signature(secret: str, timestamp: str, body: str = "") -> str:
    """Calculate HMAC signature for a request.

    Args:
        secret: The HMAC secret key
        timestamp: Unix timestamp as string
        body: Request body (optional)

    Returns:
        Hex digest of the HMAC signature
    """
    message = f"{timestamp}:{body}"
    return hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()


def validate_hmac_request(
    request_signature: str,
    request_timestamp: str,
    secret: str,
    body: str = "",
    window_seconds: int = 300,
) -> tuple[bool, Optional[str]]:
    """Validate an HMAC-authenticated request.

    Args:
        request_signature: The HMAC signature from the request
        request_timestamp: The timestamp from the request
        secret: The HMAC secret key
        body: Request body (optional)
        window_seconds: Time window for valid requests (default: 5 minutes)

    Returns:
        Tuple of (is_valid, error_message)
    """
    # Check timestamp
    try:
        timestamp_int = int(request_timestamp)
        current_time = int(time.time())
        if abs(current_time - timestamp_int) > window_seconds:
            return False, "Request timestamp expired"
    except ValueError:
        return False, "Invalid timestamp"

    # Calculate expected signature
    expected_signature = calculate_hmac_signature(secret, request_timestamp, body)

    # Use constant-time comparison for security
    if not hmac.compare_digest(request_signature.lower(), expected_signature.lower()):
        return False, "Invalid HMAC signature"

    return True, None


def create_hmac_headers(secret: str, body: str = "") -> dict[str, str]:
    """Create HMAC headers for a request.

    Args:
        secret: The HMAC secret key
        body: Request body (optional)

    Returns:
        Dictionary of headers to add to the request
    """
    timestamp = str(int(time.time()))
    signature = calculate_hmac_signature(secret, timestamp, body)

    return {
        security_config.hmac_header: signature,
        security_config.hmac_timestamp_header: timestamp,
    }
