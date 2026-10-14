"""Advisory, expiring edit leases on resolution work items (P6-08)."""

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dada_api.core.errors import ApiError
from dada_api.models.batch import AnnotationBatch, BatchItem
from dada_api.models.consensus import ResolutionWorkItem, ResolutionWorkStatus
from dada_api.models.project import Project
from dada_api.models.resolution import ResolutionLease
from dada_api.models.user import User
from dada_api.services import audit

LEASE_DURATION = timedelta(minutes=15)
LEASE_CAP = timedelta(hours=2)


async def load_work_item(
    session: AsyncSession, project: Project, work_item_id: str, *, lock: bool = False
) -> ResolutionWorkItem:
    """Return a work item of the project, never revealing another project's.

    Args:
        session: Active database session.
        project: Authorized project.
        work_item_id: Work item identifier.
        lock: Whether to lock the row for the caller's transaction.

    Returns:
        The work item.

    Raises:
        ApiError: 404 when it does not exist in this project.
    """
    query = (
        select(ResolutionWorkItem)
        .join(BatchItem, BatchItem.id == ResolutionWorkItem.batch_item_id)
        .join(AnnotationBatch, AnnotationBatch.id == BatchItem.batch_id)
        .where(
            ResolutionWorkItem.id == work_item_id,
            AnnotationBatch.project_id == project.id,
        )
    )
    if lock:
        query = query.with_for_update(of=ResolutionWorkItem)
    work_item = await session.scalar(query)
    if work_item is None:
        raise ApiError(404, "not_found", "The resolution work item does not exist.")
    return work_item


async def active_lease(
    session: AsyncSession, work_item_id: str, now: datetime
) -> ResolutionLease | None:
    """Return the work item's unexpired, unreleased lease, if any.

    Args:
        session: Active database session.
        work_item_id: Work item identifier.
        now: Server time.

    Returns:
        The active lease, or None.
    """
    return await session.scalar(
        select(ResolutionLease).where(
            ResolutionLease.work_item_id == work_item_id,
            ResolutionLease.released_at.is_(None),
            ResolutionLease.expires_at > now,
        )
    )


async def foreign_lease(
    session: AsyncSession, item_id: str, user: User, now: datetime
) -> ResolutionLease | None:
    """Return an active lease another user holds on any work item of an image.

    Retry, acceptance, cancellation, and adjudication are blocked while one
    exists, because they would overwrite that user's edit.

    Args:
        session: Active database session.
        item_id: Batch item identifier.
        user: Caller.
        now: Server time.

    Returns:
        The conflicting lease, or None.
    """
    return await session.scalar(
        select(ResolutionLease)
        .join(
            ResolutionWorkItem,
            ResolutionWorkItem.id == ResolutionLease.work_item_id,
        )
        .where(
            ResolutionWorkItem.batch_item_id == item_id,
            ResolutionLease.released_at.is_(None),
            ResolutionLease.expires_at > now,
            ResolutionLease.holder_id != user.id,
        )
    )


def lease_conflict(lease: ResolutionLease) -> ApiError:
    """Return the conflict raised while another user holds a lease.

    Args:
        lease: The conflicting lease.

    Returns:
        The ``409 lease_held`` error naming the holder and expiry.
    """
    return ApiError(
        409,
        "lease_held",
        "Another owner or manager is editing this case.",
        details={
            "holder_id": lease.holder_id,
            "expires_at": lease.expires_at.isoformat(),
        },
    )


async def acquire(
    session: AsyncSession,
    actor: User,
    project: Project,
    work_item_id: str,
    now: datetime,
) -> ResolutionLease:
    """Acquire or renew the caller's edit lease on a work item.

    A renewal extends the lease by 15 minutes but never past two hours after
    it was first acquired; past that, the holder releases and acquires again.
    An expired lease is closed here, so no sweeper is needed.

    Args:
        session: Active database session.
        actor: Owner or manager requesting the lease.
        project: Authorized project.
        work_item_id: Work item to edit.
        now: Server time.

    Returns:
        The caller's active lease.

    Raises:
        ApiError: 404 when the work item is unknown; 409 ``work_item_not_open``
            unless it awaits an expert, ``lease_held`` while another user holds
            it, and ``lease_cap_reached`` after two continuous hours.
    """
    work_item = await load_work_item(session, project, work_item_id, lock=True)
    if work_item.status != ResolutionWorkStatus.review_required:
        raise ApiError(
            409, "work_item_not_open", "The case does not await an expert decision."
        )
    open_lease = await session.scalar(
        select(ResolutionLease).where(
            ResolutionLease.work_item_id == work_item.id,
            ResolutionLease.released_at.is_(None),
        )
    )
    if open_lease is not None and open_lease.expires_at <= now:
        open_lease.released_at = open_lease.expires_at
        await session.flush()
        open_lease = None

    if open_lease is not None and open_lease.holder_id != actor.id:
        raise lease_conflict(open_lease)
    if open_lease is not None:
        if now >= open_lease.cap_at:
            raise ApiError(
                409,
                "lease_cap_reached",
                "The lease reached its two-hour limit; release and acquire it again.",
            )
        open_lease.renewed_at = now
        open_lease.expires_at = min(now + LEASE_DURATION, open_lease.cap_at)
        lease = open_lease
    else:
        lease = ResolutionLease(
            work_item_id=work_item.id,
            holder_id=actor.id,
            acquired_at=now,
            renewed_at=now,
            expires_at=now + LEASE_DURATION,
            cap_at=now + LEASE_CAP,
        )
        session.add(lease)
    await session.commit()
    await session.refresh(lease)
    return lease


async def release(
    session: AsyncSession,
    actor: User,
    project: Project,
    work_item_id: str,
    now: datetime,
) -> None:
    """Release the caller's lease on a work item; releasing nothing is fine.

    Args:
        session: Active database session.
        actor: Lease holder.
        project: Authorized project.
        work_item_id: Work item being left.
        now: Server time.
    """
    work_item = await load_work_item(session, project, work_item_id, lock=True)
    lease = await active_lease(session, work_item.id, now)
    if lease is not None and lease.holder_id == actor.id:
        lease.released_at = now
    await session.commit()


async def revoke(
    session: AsyncSession,
    actor: User,
    project: Project,
    work_item_id: str,
    reason: str,
    now: datetime,
) -> None:
    """Revoke an abandoned lease with an audited reason.

    The holder's local recovery draft lives in their browser and is never
    touched; their next submit simply needs a lease again.

    Args:
        session: Active database session.
        actor: Owner or manager revoking.
        project: Authorized project.
        work_item_id: Work item whose lease is revoked.
        reason: Mandatory explanation.
        now: Server time.

    Raises:
        ApiError: 404 when no active lease exists.
    """
    work_item = await load_work_item(session, project, work_item_id, lock=True)
    lease = await active_lease(session, work_item.id, now)
    if lease is None:
        raise ApiError(404, "not_found", "The case has no active lease.")
    lease.released_at = now
    lease.revoked_by = actor.id
    lease.revoke_reason = reason
    audit.record(
        session,
        actor,
        project.id,
        "resolution_lease.revoked",
        "resolution_lease",
        lease.id,
        before={
            "holder_id": lease.holder_id,
            "expires_at": lease.expires_at.isoformat(),
        },
        after={"work_item_id": work_item.id, "reason": reason},
    )
    await session.commit()
