"""Operator listing, quarantine, and audited release of resolver pipeline versions."""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dada_api.consensus import catalog
from dada_api.models.resolution import ResolverQuarantine
from dada_api.models.user import User
from dada_api.services import audit

OPERATOR_REASON = "operator"


class QuarantineError(Exception):
    """An operator quarantine command that cannot be carried out."""


def _task_type(key: str) -> tuple[str, str, str]:
    """Return the identifier, version, and task type of an installed pipeline key.

    Raises:
        QuarantineError: When the key names no installed pipeline version.
    """
    identifier, _, version = key.partition("@")
    task_type = next(
        (task for task, entry in catalog.PIPELINES.items() if entry.id == identifier),
        None,
    )
    if task_type is None or version != catalog.VERSION:
        raise QuarantineError(f"No installed pipeline is {key!r}.")
    return identifier, version, task_type


async def _operator(session: AsyncSession, username: str) -> User:
    """Return the active administrator an operator command is recorded under.

    Raises:
        QuarantineError: When the username is not an active administrator.
    """
    operator = await session.scalar(
        select(User).where(
            User.username == username,
            User.is_administrator.is_(True),
            User.is_active.is_(True),
        )
    )
    if operator is None:
        raise QuarantineError(f"{username!r} is not an active administrator.")
    return operator


async def _open(
    session: AsyncSession, identifier: str, version: str
) -> ResolverQuarantine | None:
    """Return the open quarantine of one pipeline version, if any."""
    return await session.scalar(
        select(ResolverQuarantine).where(
            ResolverQuarantine.identifier == identifier,
            ResolverQuarantine.version == version,
            ResolverQuarantine.released_at.is_(None),
        )
    )


async def list_open(session: AsyncSession) -> list[ResolverQuarantine]:
    """Return every open quarantine, oldest first.

    Args:
        session: Active database session.

    Returns:
        The quarantines that currently block dispatch.
    """
    return list(
        await session.scalars(
            select(ResolverQuarantine)
            .where(ResolverQuarantine.released_at.is_(None))
            .order_by(ResolverQuarantine.triggered_at, ResolverQuarantine.id)
        )
    )


async def quarantine(
    session: AsyncSession, key: str, reason: str, username: str, now: datetime
) -> ResolverQuarantine:
    """Quarantine a faulty pipeline version on an operator's decision.

    Args:
        session: Active database session; committed here.
        key: ``identifier@version`` of an installed pipeline.
        reason: The operator's audit reason.
        username: Active administrator recorded as the actor.
        now: Server time.

    Returns:
        The open quarantine.

    Raises:
        QuarantineError: When the key is unknown, the operator is not an
            active administrator, or the version is already quarantined.
    """
    identifier, version, _ = _task_type(key)
    operator = await _operator(session, username)
    if await _open(session, identifier, version) is not None:
        raise QuarantineError(f"{key!r} is already quarantined.")
    entry = ResolverQuarantine(
        identifier=identifier,
        version=version,
        reason=OPERATOR_REASON,
        triggered_at=now,
    )
    session.add(entry)
    await session.flush()
    audit.record(
        session,
        operator,
        None,
        "resolver.quarantined",
        "resolver_quarantine",
        entry.id,
        after={"identifier": identifier, "version": version, "reason": reason},
    )
    await session.commit()
    return entry


async def release(
    session: AsyncSession, key: str, reason: str, username: str, now: datetime
) -> ResolverQuarantine:
    """Release a quarantine once the pipeline's health fixture passes.

    Args:
        session: Active database session; committed here.
        key: ``identifier@version`` of an installed pipeline.
        reason: The operator's audit reason.
        username: Active administrator recorded as the releaser.
        now: Server time.

    Returns:
        The released quarantine.

    Raises:
        QuarantineError: When the key is unknown or not quarantined, the
            operator is not an active administrator, or the health fixture
            fails, in which case the quarantine stays open.
    """
    from dada_api.consensus import health

    identifier, version, task_type = _task_type(key)
    operator = await _operator(session, username)
    entry = await _open(session, identifier, version)
    if entry is None:
        raise QuarantineError(f"{key!r} is not quarantined.")
    if not health.passes(task_type):
        raise QuarantineError(f"The health fixture of {key!r} failed.")
    entry.released_at = now
    entry.released_by = operator.id
    entry.release_reason = reason
    audit.record(
        session,
        operator,
        None,
        "resolver.quarantine_released",
        "resolver_quarantine",
        entry.id,
        before={"identifier": identifier, "version": version, "reason": entry.reason},
        after={"released_at": now.isoformat(), "reason": reason},
    )
    await session.commit()
    return entry
