"""Refresh session issuance, rotation, replay detection, and revocation."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from dada_api.core.config import get_settings
from dada_api.core.errors import ApiError
from dada_api.core.security import create_refresh_token, hash_refresh_token
from dada_api.models.refresh_session import RefreshSession
from dada_api.models.user import User


def _build_session(user: User, family_id: str) -> tuple[RefreshSession, str]:
    """Build an unsaved refresh session and return it with its plaintext token.

    Args:
        user: Owner of the credential.
        family_id: Rotation family the credential belongs to.

    Returns:
        The unsaved record and the plaintext token to send to the client.
    """
    settings = get_settings()
    token, token_hash = create_refresh_token()
    record = RefreshSession(
        family_id=family_id,
        user_id=user.id,
        token_hash=token_hash,
        expires_at=datetime.now(UTC)
        + timedelta(days=settings.refresh_token_expire_days),
    )
    return record, token


async def issue_refresh_session(session: AsyncSession, user: User) -> str:
    """Start a new rotation family for a user and return its refresh token.

    Args:
        session: Active database session.
        user: Authenticated user logging in.

    Returns:
        The plaintext refresh token.
    """
    record, token = _build_session(user, str(uuid4()))
    session.add(record)
    await session.commit()
    return token


async def rotate_refresh_session(
    session: AsyncSession,
    presented_token: str,
) -> tuple[User, str]:
    """Rotate a presented refresh credential into its successor.

    Args:
        session: Active database session.
        presented_token: Refresh token supplied by the client.

    Returns:
        The owning user and the successor refresh token.

    Raises:
        ApiError: 401 when the credential is unknown, expired, or replayed.
    """
    record = await session.scalar(
        select(RefreshSession).where(
            RefreshSession.token_hash == hash_refresh_token(presented_token)
        )
    )
    if record is None:
        raise ApiError(401, "invalid_refresh_token", "The refresh token is invalid.")

    if record.revoked_at is not None:
        await revoke_refresh_family(session, record.family_id)
        raise ApiError(
            401,
            "refresh_token_replayed",
            "The refresh token was already used. The session has been revoked.",
        )

    if record.expires_at <= datetime.now(UTC):
        raise ApiError(401, "refresh_token_expired", "The refresh token has expired.")

    user = await session.get(User, record.user_id)
    if user is None or not user.is_active:
        raise ApiError(401, "invalid_refresh_token", "The refresh token is invalid.")

    record.revoked_at = datetime.now(UTC)
    successor, token = _build_session(user, record.family_id)
    session.add(successor)
    await session.commit()
    return user, token


async def revoke_refresh_family(session: AsyncSession, family_id: str) -> None:
    """Revoke every credential in a rotation family.

    Args:
        session: Active database session.
        family_id: Rotation family to revoke.
    """
    await session.execute(
        update(RefreshSession)
        .where(
            RefreshSession.family_id == family_id,
            RefreshSession.revoked_at.is_(None),
        )
        .values(revoked_at=datetime.now(UTC))
    )
    await session.commit()


async def revoke_presented_session(
    session: AsyncSession,
    presented_token: str,
) -> None:
    """Revoke the rotation family owning a presented credential.

    Args:
        session: Active database session.
        presented_token: Refresh token supplied by the client.
    """
    record = await session.scalar(
        select(RefreshSession).where(
            RefreshSession.token_hash == hash_refresh_token(presented_token)
        )
    )
    if record is not None:
        await revoke_refresh_family(session, record.family_id)
