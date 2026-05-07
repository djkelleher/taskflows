import hashlib
import hmac
import json
import secrets
import threading
import time
from contextlib import contextmanager
from typing import List, Optional

from pydantic import BaseModel
from taskflows.common import secure_write_text, services_data_dir


_hmac_nonce_lock = threading.Lock()
_csrf_token_lock = threading.Lock()
_hmac_nonces_file = services_data_dir / "hmac_nonces.json"
_csrf_tokens_file = services_data_dir / "csrf_tokens.json"


# Security configuration
class SecurityConfig(BaseModel):
    """Security configuration for the Services API."""

    # HMAC authentication
    enable_hmac: bool = True
    hmac_secret: str = ""
    hmac_header: str = "X-HMAC-Signature"
    hmac_timestamp_header: str = "X-Timestamp"
    hmac_nonce_header: str = "X-Nonce"
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
    allowed_headers: List[str] = [
        "Authorization",
        "Content-Type",
        "X-CSRF-Token",
        "X-HMAC-Signature",
        "X-Timestamp",
        "X-Nonce",
    ]

    # Additional security headers
    enable_security_headers: bool = True

    # Logging
    log_security_events: bool = True


config_file = services_data_dir / "security.json"


@contextmanager
def _locked_json_store(path, process_lock, default_factory=dict):
    """Load/update a JSON store while holding thread and process locks."""
    lock_path = path.with_suffix(path.suffix + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with process_lock:
        with open(lock_path, "a+") as lock_file:
            try:
                import fcntl

                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            except ImportError:
                fcntl = None

            try:
                if path.exists():
                    try:
                        data = json.loads(path.read_text())
                    except json.JSONDecodeError as exc:
                        raise RuntimeError(
                            f"Security state file {path} is corrupt; refusing to reset it"
                        ) from exc
                    if not isinstance(data, dict):
                        raise RuntimeError(
                            f"Security state file {path} must contain a JSON object"
                        )
                else:
                    data = default_factory()
                original_data = json.dumps(data, sort_keys=True, default=str)
                yield data
                if json.dumps(data, sort_keys=True, default=str) != original_data:
                    secure_write_text(path, json.dumps(data, indent=2, default=str))
            finally:
                if fcntl is not None:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def load_security_config() -> SecurityConfig:
    """Load security configuration from file."""
    if config_file.exists():
        return SecurityConfig(**json.loads(config_file.read_text()))
    return SecurityConfig()


security_config = load_security_config()


def save_security_config(config: SecurityConfig):
    """Save security configuration to file."""
    secure_write_text(config_file, json.dumps(config.model_dump()))


def generate_hmac_secret() -> str:
    """Generate a secure HMAC secret."""
    return secrets.token_urlsafe(32)


def _canonical_hmac_message(
    timestamp: str,
    body: str = "",
    *,
    method: Optional[str] = None,
    path: Optional[str] = None,
    query_string: str = "",
    nonce: Optional[str] = None,
) -> str:
    """Build the canonical message signed by HMAC."""
    if method is None or path is None or nonce is None:
        raise ValueError("HMAC method, path, and nonce are required")
    return "\n".join(
        [
            timestamp,
            nonce,
            method.upper(),
            path,
            query_string or "",
            body or "",
        ]
    )


def calculate_hmac_signature(
    secret: str,
    timestamp: str,
    body: str = "",
    *,
    method: Optional[str] = None,
    path: Optional[str] = None,
    query_string: str = "",
    nonce: Optional[str] = None,
) -> str:
    """Calculate HMAC signature for a request.

    Args:
        secret: The HMAC secret key
        timestamp: Unix timestamp as string
        body: Request body (optional)

    Returns:
        Hex digest of the HMAC signature
    """
    message = _canonical_hmac_message(
        timestamp,
        body,
        method=method,
        path=path,
        query_string=query_string,
        nonce=nonce,
    )
    return hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()


def _is_nonce_available(
    nonce: Optional[str], window_seconds: int
) -> tuple[bool, Optional[str]]:
    if not nonce:
        return False, "HMAC nonce required"

    current_time = int(time.time())
    with _locked_json_store(_hmac_nonces_file, _hmac_nonce_lock) as nonces:
        expired = [
            n
            for n, ts in nonces.items()
            if abs(current_time - int(ts)) > window_seconds
        ]
        for old_nonce in expired:
            nonces.pop(old_nonce, None)

        if nonce in nonces:
            return False, "HMAC nonce already used"
    return True, None


def _store_nonce(nonce: str, timestamp_int: int) -> None:
    with _locked_json_store(_hmac_nonces_file, _hmac_nonce_lock) as nonces:
        if nonce in nonces:
            raise ValueError("HMAC nonce already used")
        nonces[nonce] = timestamp_int


def validate_hmac_request(
    request_signature: str,
    request_timestamp: str,
    secret: str,
    body: str = "",
    window_seconds: int = 300,
    *,
    method: Optional[str] = None,
    path: Optional[str] = None,
    query_string: str = "",
    nonce: Optional[str] = None,
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

    if method is not None and path is not None and not nonce:
        return False, "HMAC nonce required"

    # Calculate expected signature
    expected_signature = calculate_hmac_signature(
        secret,
        request_timestamp,
        body,
        method=method,
        path=path,
        query_string=query_string,
        nonce=nonce,
    )

    # Use constant-time comparison for security
    if not hmac.compare_digest(request_signature.lower(), expected_signature.lower()):
        return False, "Invalid HMAC signature"

    if method is not None and path is not None:
        nonce_valid, nonce_error = _is_nonce_available(nonce, window_seconds)
        if not nonce_valid:
            return False, nonce_error
        try:
            _store_nonce(nonce, timestamp_int)
        except ValueError as exc:
            return False, str(exc)

    return True, None


def create_hmac_headers(
    secret: str,
    body: str = "",
    *,
    method: Optional[str] = None,
    path: Optional[str] = None,
    query_string: str = "",
) -> dict[str, str]:
    """Create HMAC headers for a request.

    Args:
        secret: The HMAC secret key
        body: Request body (optional)

    Returns:
        Dictionary of headers to add to the request
    """
    timestamp = str(int(time.time()))
    nonce = secrets.token_urlsafe(24)
    signature = calculate_hmac_signature(
        secret,
        timestamp,
        body,
        method=method,
        path=path,
        query_string=query_string,
        nonce=nonce,
    )

    return {
        security_config.hmac_header: signature,
        security_config.hmac_timestamp_header: timestamp,
        security_config.hmac_nonce_header: nonce,
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

    return {
        "token": token,
        "expiry": expiry,
        "signature": signature,
        "username": username,
    }


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
    if not token or not username or not signature:
        return False, "Invalid CSRF token data"

    # Check expiry
    try:
        expiry_int = int(expiry)
    except (TypeError, ValueError):
        return False, "Invalid CSRF token expiry"

    if int(time.time()) > expiry_int:
        return False, "CSRF token expired"

    # Verify signature
    expected_message = f"{token}:{username}:{expiry_int}"
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
    current_time = int(time.time())
    with _locked_json_store(_csrf_tokens_file, _csrf_token_lock) as tokens:
        expired_users = [
            u for u, data in tokens.items() if int(data.get("expiry", 0)) < current_time
        ]
        for user in expired_users:
            del tokens[user]

        tokens[token_data["token"]] = token_data


def get_csrf_token_data(username: str, token: Optional[str] = None) -> Optional[dict]:
    """Retrieve CSRF token data for a user.

    Args:
        username: The username

    Returns:
        Token data dict or None if not found/expired
    """
    current_time = int(time.time())
    with _locked_json_store(_csrf_tokens_file, _csrf_token_lock) as tokens:
        expired = [
            stored_token
            for stored_token, data in tokens.items()
            if int(data.get("expiry", 0)) <= current_time
        ]
        for stored_token in expired:
            del tokens[stored_token]

        if token:
            token_data = tokens.get(token)
            if token_data and token_data.get("username") == username:
                return token_data
        else:
            for token_data in tokens.values():
                if token_data.get("username") == username:
                    return token_data
    return None


def remove_csrf_token(username: str, token: Optional[str] = None) -> None:
    """Remove CSRF token for a user (e.g., on logout).

    Args:
        username: The username
    """
    with _locked_json_store(_csrf_tokens_file, _csrf_token_lock) as tokens:
        if token:
            token_data = tokens.get(token)
            if token_data and token_data.get("username") == username:
                tokens.pop(token, None)
        else:
            for stored_token, token_data in list(tokens.items()):
                if token_data.get("username") == username:
                    tokens.pop(stored_token, None)
