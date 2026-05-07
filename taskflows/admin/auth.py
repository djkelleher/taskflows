import json
import os
import secrets
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional

import jwt
from passlib.context import CryptContext
from pydantic import BaseModel

from taskflows.common import logger, secure_write_text, services_data_dir
from taskflows.admin.security import _locked_json_store

# Environment variable names for credentials
ENV_ADMIN_USER = "TF_ADMIN_USER"
ENV_ADMIN_PASSWORD = "TF_ADMIN_PASSWORD"
ENV_JWT_SECRET = "TF_JWT_SECRET"

# JWT configuration
JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60
REFRESH_TOKEN_EXPIRE_DAYS = 7

# Password hashing - using argon2id (recommended by OWASP) with bcrypt fallback for legacy hashes
pwd_context = CryptContext(schemes=["argon2", "bcrypt"], deprecated="auto")

# File paths
ui_config_file = services_data_dir / "ui_config.json"
users_file = services_data_dir / "users.json"
refresh_tokens_file = services_data_dir / "refresh_tokens.json"
_refresh_token_lock = threading.Lock()


class User(BaseModel):
    """User model for authentication."""

    username: str
    password_hash: str
    role: str = "admin"
    created_at: datetime
    last_login: Optional[datetime] = None


class JWTToken(BaseModel):
    """JWT token response model."""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = ACCESS_TOKEN_EXPIRE_MINUTES * 60


class LoginRequest(BaseModel):
    """Login request model."""

    username: str
    password: str


class TokenPayload(BaseModel):
    """JWT token payload model."""

    sub: str
    exp: datetime
    iat: datetime
    type: str
    jti: Optional[str] = None


class UIConfig(BaseModel):
    """UI configuration model."""

    enabled: bool = False
    jwt_secret: str = ""
    cors_origins: list[str] = ["http://localhost:3000"]


def generate_jwt_secret() -> str:
    """Generate a secure JWT secret."""
    return secrets.token_urlsafe(32)


def _load_json_object(path, label: str) -> dict:
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{label} {path} is not valid JSON") from exc
    if not isinstance(data, dict):
        raise RuntimeError(f"{label} {path} must contain a JSON object")
    return data


def load_ui_config() -> UIConfig:
    """Load UI configuration from file or environment variables.

    Environment variable TF_JWT_SECRET takes precedence over file config.
    """
    config = UIConfig()
    if ui_config_file.exists():
        config = UIConfig(**_load_json_object(ui_config_file, "UI config"))

    # Environment variable takes precedence
    env_jwt_secret = os.getenv(ENV_JWT_SECRET)
    if env_jwt_secret:
        config.jwt_secret = env_jwt_secret
        config.enabled = True
        logger.debug("Using JWT secret from environment variable")

    return config


def save_ui_config(config: UIConfig) -> None:
    """Save UI configuration to file."""
    secure_write_text(
        ui_config_file, json.dumps(config.model_dump(), indent=2, default=str)
    )


def load_users() -> Dict[str, User]:
    """Load users from file."""
    if users_file.exists():
        users_data = _load_json_object(users_file, "Users file")
        return {
            username: User(**user_data) for username, user_data in users_data.items()
        }
    return {}


def save_users(users: Dict[str, User]) -> None:
    """Save users to file."""
    users_data = {
        username: user.model_dump(mode="json") for username, user in users.items()
    }
    secure_write_text(users_file, json.dumps(users_data, indent=2, default=str))


def _cleanup_refresh_tokens(tokens: Dict[str, dict]) -> None:
    current_time = int(time.time())
    expired = [
        token_id
        for token_id, data in tokens.items()
        if int(data.get("exp", 0)) <= current_time
    ]
    for token_id in expired:
        tokens.pop(token_id, None)


def _store_refresh_token(token_id: str, username: str, expires_at: int) -> None:
    with _locked_json_store(refresh_tokens_file, _refresh_token_lock) as tokens:
        _cleanup_refresh_tokens(tokens)
        tokens[token_id] = {
            "username": username,
            "exp": expires_at,
            "revoked": False,
            "created_at": int(time.time()),
        }


def _is_refresh_token_active(token_id: str, username: str) -> bool:
    with _locked_json_store(refresh_tokens_file, _refresh_token_lock) as tokens:
        _cleanup_refresh_tokens(tokens)
        token_data = tokens.get(token_id)
        if not token_data:
            return False
        if token_data.get("revoked"):
            return False
        if token_data.get("username") != username:
            return False
        return int(token_data.get("exp", 0)) > int(time.time())


def revoke_refresh_token(refresh_token: str, jwt_secret: str) -> bool:
    """Revoke a refresh token by its JWT ID."""
    try:
        payload = jwt.decode(refresh_token, jwt_secret, algorithms=[JWT_ALGORITHM])
    except jwt.InvalidTokenError as exc:
        logger.warning(f"Cannot revoke invalid refresh token: {exc}")
        return False

    if payload.get("type") != "refresh":
        return False
    token_id = payload.get("jti")
    if not token_id:
        return False

    revoked = False
    with _locked_json_store(refresh_tokens_file, _refresh_token_lock) as tokens:
        _cleanup_refresh_tokens(tokens)
        if token_id in tokens:
            tokens[token_id]["revoked"] = True
            revoked = True
    return revoked


def create_admin_user(username: str, password: str) -> User:
    """Create an admin user."""
    users = load_users()

    if username in users:
        logger.warning(f"User {username} already exists, updating password")

    password_hash = pwd_context.hash(password)
    user = User(
        username=username,
        password_hash=password_hash,
        role="admin",
        created_at=datetime.now(timezone.utc),
    )

    users[username] = user
    save_users(users)

    logger.info(f"Admin user {username} created successfully")
    return user


def get_user(username: str) -> Optional[User]:
    """Get a user by username."""
    users = load_users()
    return users.get(username)


def update_user_last_login(username: str) -> None:
    """Update user's last login timestamp."""
    users = load_users()
    if username in users:
        users[username].last_login = datetime.now(timezone.utc)
        save_users(users)


def _authenticate_and_update_login(username: str, password: str) -> Optional[User]:
    """Authenticate a file-based user and update last_login in one read+write."""
    users = load_users()
    user = users.get(username)
    if not user:
        logger.warning(f"User {username} not found")
        return None
    if not verify_password(password, user.password_hash):
        logger.warning(f"Invalid password for user {username}")
        return None
    user.last_login = datetime.now(timezone.utc)
    save_users(users)
    return user


def verify_password(plain_password: str, password_hash: str) -> bool:
    """Verify a password against a hash."""
    try:
        return pwd_context.verify(plain_password, password_hash)
    except (ValueError, TypeError) as exc:
        logger.warning(f"Password hash verification failed: {exc}")
        return False


def create_access_token(username: str, jwt_secret: str) -> str:
    """Create a JWT access token."""
    expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {
        "sub": username,
        "exp": expire,
        "iat": datetime.now(timezone.utc),
        "type": "access",
    }
    return jwt.encode(payload, jwt_secret, algorithm=JWT_ALGORITHM)


def create_refresh_token(username: str, jwt_secret: str) -> str:
    """Create a JWT refresh token."""
    expire = datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    token_id = uuid.uuid4().hex
    payload = {
        "sub": username,
        "exp": expire,
        "iat": datetime.now(timezone.utc),
        "type": "refresh",
        "jti": token_id,
    }
    token = jwt.encode(payload, jwt_secret, algorithm=JWT_ALGORITHM)
    _store_refresh_token(token_id, username, int(expire.timestamp()))
    return token


def verify_token(
    token: str, jwt_secret: str, token_type: str = "access"
) -> Optional[str]:
    """Verify a JWT token and return the username if valid."""
    try:
        payload = jwt.decode(token, jwt_secret, algorithms=[JWT_ALGORITHM])
        if payload.get("type") != token_type:
            logger.warning(
                f"Token type mismatch: expected {token_type}, got {payload.get('type')}"
            )
            return None
        username = payload.get("sub")
        if token_type == "refresh":
            token_id = payload.get("jti")
            if (
                not token_id
                or not username
                or not _is_refresh_token_active(token_id, username)
            ):
                logger.warning("Refresh token is revoked or unknown")
                return None
        return username
    except jwt.ExpiredSignatureError:
        logger.debug("Token has expired")
        return None
    except jwt.InvalidTokenError as e:
        logger.warning(f"Invalid token: {e}")
        return None


def authenticate_user(username: str, password: str) -> Optional[User]:
    """Authenticate a user with username and password.

    Checks environment variables TF_ADMIN_USER and TF_ADMIN_PASSWORD first,
    then falls back to file-based users.
    """
    # Check environment variable credentials first
    env_user = os.getenv(ENV_ADMIN_USER)
    env_password = os.getenv(ENV_ADMIN_PASSWORD)

    if env_user and env_password:
        if username == env_user and secrets.compare_digest(password, env_password):
            logger.debug("User authenticated via environment variables")
            return User(
                username=username,
                password_hash="",  # Not needed for env-based auth
                role="admin",
                created_at=datetime.now(timezone.utc),
            )
        # If env vars are set but don't match, still check file-based users
        # This allows both methods to coexist

    # Fall back to file-based users
    return _authenticate_and_update_login(username, password)
