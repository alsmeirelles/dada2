"""Password hashing, refresh credential, and JWT helpers."""

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

from jose import JWTError, jwt
from pwdlib import PasswordHash

from dada_api.core.config import get_settings

password_hasher = PasswordHash.recommended()
REFRESH_TOKEN_BYTES = 48


def hash_password(password: str) -> str:
    """Hash a plaintext password with the recommended password hasher."""
    return password_hasher.hash(password)


def verify_password(plain_password: str, password_hash: str) -> bool:
    """Return whether a plaintext password matches a stored password hash."""
    return password_hasher.verify(plain_password, password_hash)


def hash_refresh_token(token: str) -> str:
    """Return the storage hash of a refresh token.

    Refresh tokens are high-entropy random values, so a single SHA-256 pass is
    enough to keep the database free of usable credentials.

    Args:
        token: Plaintext refresh token.

    Returns:
        The hexadecimal digest stored in the database.
    """
    return hashlib.sha256(token.encode()).hexdigest()


def create_refresh_token() -> tuple[str, str]:
    """Create a refresh token and its storage hash.

    Returns:
        The plaintext token to send to the client and the hash to persist.
    """
    token = secrets.token_urlsafe(REFRESH_TOKEN_BYTES)
    return token, hash_refresh_token(token)


def create_access_token(subject: str, roles: list[str]) -> str:
    """Create a signed JWT access token for a user subject and role list."""
    settings = get_settings()
    expires_delta = timedelta(minutes=settings.access_token_expire_minutes)
    expires_at = datetime.now(UTC) + expires_delta
    payload: dict[str, Any] = {
        "sub": subject,
        "roles": roles,
        "exp": expires_at,
        "iat": datetime.now(UTC),
        "type": "access",
    }
    return jwt.encode(
        payload,
        settings.jwt_secret_key.get_secret_value(),
        algorithm=settings.jwt_algorithm,
    )


def decode_access_token(token: str) -> dict[str, Any]:
    """Decode and validate a JWT access token."""
    settings = get_settings()
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key.get_secret_value(),
            algorithms=[settings.jwt_algorithm],
        )
    except JWTError as error:
        raise ValueError("Invalid access token.") from error

    if payload.get("type") != "access" or not payload.get("sub"):
        raise ValueError("Invalid access token.")

    return payload
