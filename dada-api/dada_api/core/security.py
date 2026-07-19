"""Password hashing and JWT helpers."""

from datetime import UTC, datetime, timedelta
from typing import Any

from jose import JWTError, jwt
from pwdlib import PasswordHash

from dada_api.core.config import get_settings

password_hasher = PasswordHash.recommended()


def hash_password(password: str) -> str:
    """Hash a plaintext password with the recommended password hasher."""
    return password_hasher.hash(password)


def verify_password(plain_password: str, password_hash: str) -> bool:
    """Return whether a plaintext password matches a stored password hash."""
    return password_hasher.verify(plain_password, password_hash)


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
