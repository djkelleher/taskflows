import hashlib
import json
import os
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Optional

import jwt
from passlib.context import CryptContext
from pydantic import BaseModel

from taskflows.common import logger, services_data_dir

# Environment variable names for credentials
ENV_ADMIN_USER = "TF_ADMIN_USER"
ENV_ADMIN_PASSWORD = "TF_ADMIN_PASSWORD"
ENV_JWT_SECRET = "TF_JWT_SECRET"

# JWT configuration
JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60
REFRESH_TOKEN_EXPIRE_DAYS = 7

# Password hashing
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# File paths
ui_config_file = services_data_dir / "ui_config.json"
users_file = services_data_dir / "users.json"


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


class UIConfig(BaseModel):
    """UI configuration model."""

    enabled: bool = False
    jwt_secret: str = ""
    cors_origins: list[str] = ["http://localhost:3000"]


def generate_jwt_secret() -> str:
    """Generate a secure JWT secret."""
    return secrets.token_urlsafe(32)


def load_ui_config() -> UIConfig:
    """Load UI configuration from file or environment variables.

    Environment variable TF_JWT_SECRET takes precedence over file config.
    """
    config = UIConfig()
    if ui_config_file.exists():
        config = UIConfig(**json.loads(ui_config_file.read_text()))

    # Environment variable takes precedence
    env_jwt_secret = os.getenv(ENV_JWT_SECRET)
    if env_jwt_secret:
        config.jwt_secret = env_jwt_secret
        config.enabled = True
        logger.debug("Using JWT secret from environment variable")

    return config


def save_ui_config(config: UIConfig) -> None:
    """Save UI configuration to file."""
    ui_config_file.parent.mkdir(parents=True, exist_ok=True)
    ui_config_file.write_text(json.dumps(config.model_dump(), indent=2, default=str))


def load_users() -> Dict[str, User]:
    """Load users from file."""
    if users_file.exists():
        users_data = json.loads(users_file.read_text())
        return {
            username: User(**user_data) for username, user_data in users_data.items()
        }
    return {}


def save_users(users: Dict[str, User]) -> None:
    """Save users to file."""
    users_file.parent.mkdir(parents=True, exist_ok=True)
    users_data = {
        username: user.model_dump(mode="json") for username, user in users.items()
    }
    users_file.write_text(json.dumps(users_data, indent=2, default=str))


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


def verify_password(plain_password: str, password_hash: str) -> bool:
    """Verify a password against a hash."""
    return pwd_context.verify(plain_password, password_hash)


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
    payload = {
        "sub": username,
        "exp": expire,
        "iat": datetime.now(timezone.utc),
        "type": "refresh",
    }
    return jwt.encode(payload, jwt_secret, algorithm=JWT_ALGORITHM)


def verify_token(token: str, jwt_secret: str, token_type: str = "access") -> Optional[str]:
    """Verify a JWT token and return the username if valid."""
    try:
        payload = jwt.decode(token, jwt_secret, algorithms=[JWT_ALGORITHM])
        if payload.get("type") != token_type:
            logger.warning(f"Token type mismatch: expected {token_type}, got {payload.get('type')}")
            return None
        return payload.get("sub")
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
        if username == env_user and password == env_password:
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
    user = get_user(username)
    if not user:
        logger.warning(f"User {username} not found")
        return None

    if not verify_password(password, user.password_hash):
        logger.warning(f"Invalid password for user {username}")
        return None

    return user
