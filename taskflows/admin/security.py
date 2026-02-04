import hashlib
import hmac
import json
import secrets
import time
from typing import Dict, List, Optional

from pydantic import BaseModel
from taskflows.common import services_data_dir


# In-memory CSRF token store
# In production, consider using Redis or database for scalability
_csrf_tokens: Dict[str, dict] = {}


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

    # CSRF protection (for web UI)
    enable_csrf: bool = True  # Enable by default for defense-in-depth
    csrf_header: str = "X-CSRF-Token"
    csrf_token_expiry: int = 3600  # 1 hour (shorter than JWT)

    # CORS (enabled when UI is enabled)
    enable_cors: bool = False
    allowed_origins: List[str] = ["http://localhost:3000", "http://localhost:7777"]
    allowed_methods: List[str] = ["GET", "POST", "PUT", "DELETE"]
    # Restrict allowed headers to prevent CSRF - only allow necessary headers
    allowed_headers: List[str] = ["Authorization", "Content-Type", "X-CSRF-Token"]

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


# CSRF Protection
# ===============
# Defense-in-depth measure against Cross-Site Request Forgery attacks.
# While JWT-in-header is already CSRF-resistant (browsers don't auto-send it),
# explicit CSRF tokens provide an additional security layer.

def generate_csrf_token() -> str:
    """Generate a cryptographically secure CSRF token.

    Returns:
        URL-safe random token (32 bytes encoded as base64)
    """
    return secrets.token_urlsafe(32)


def create_csrf_token_data(username: str, secret: str) -> dict:
    """Create CSRF token data with expiry and HMAC binding.

    The token is bound to the user and signed with the JWT secret to prevent
    token forgery or reuse across users.

    Args:
        username: The username to bind the token to
        secret: JWT secret for signing

    Returns:
        Dictionary with token, expiry, and signature
    """
    token = generate_csrf_token()
    expiry = int(time.time()) + security_config.csrf_token_expiry

    # Bind token to user and sign it
    message = f"{token}:{username}:{expiry}"
    signature = hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()

    return {"token": token, "expiry": expiry, "signature": signature, "username": username}


def validate_csrf_token(
    token: str, username: str, expiry: int, signature: str, secret: str
) -> tuple[bool, Optional[str]]:
    """Validate a CSRF token.

    Args:
        token: The CSRF token from the request header
        username: The username from JWT
        expiry: Token expiry timestamp
        signature: Token signature for integrity check
        secret: JWT secret for verification

    Returns:
        Tuple of (is_valid, error_message)
    """
    # Check expiry
    if int(time.time()) > expiry:
        return False, "CSRF token expired"

    # Verify signature
    expected_message = f"{token}:{username}:{expiry}"
    expected_signature = hmac.new(
        secret.encode(), expected_message.encode(), hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(signature, expected_signature):
        return False, "Invalid CSRF token signature"

    return True, None


def store_csrf_token(username: str, token_data: dict) -> None:
    """Store CSRF token data for a user.

    Cleans up expired tokens during storage.

    Args:
        username: The username
        token_data: Token data from create_csrf_token_data()
    """
    # Clean up expired tokens
    current_time = int(time.time())
    expired_users = [u for u, data in _csrf_tokens.items() if data["expiry"] < current_time]
    for user in expired_users:
        del _csrf_tokens[user]

    # Store new token
    _csrf_tokens[username] = token_data


def get_csrf_token_data(username: str) -> Optional[dict]:
    """Retrieve CSRF token data for a user.

    Args:
        username: The username

    Returns:
        Token data dict or None if not found/expired
    """
    token_data = _csrf_tokens.get(username)
    if token_data and token_data["expiry"] > int(time.time()):
        return token_data
    return None


def remove_csrf_token(username: str) -> None:
    """Remove CSRF token for a user (e.g., on logout).

    Args:
        username: The username
    """
    _csrf_tokens.pop(username, None)
