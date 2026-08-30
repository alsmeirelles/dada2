"""Recording of audited project changes."""

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from dada_api.core.trace import trace_id_context
from dada_api.models.audit import AuditEntry
from dada_api.models.user import User


def record(
    session: AsyncSession,
    actor: User,
    project_id: str,
    action: str,
    target_type: str,
    target_id: str | None,
    *,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
) -> None:
    """Stage an audit entry for the caller's transaction.

    The entry is added but not committed, so it reaches the database with the
    change it describes or not at all.

    Args:
        session: Active database session, committed by the caller.
        actor: User performing the change.
        project_id: Project the change belongs to.
        action: Stable name of the operation.
        target_type: Kind of resource that changed.
        target_id: Identifier of the changed resource, when it has one.
        before: State before the change, omitted for creations.
        after: State after the change, omitted for deletions.
    """
    session.add(
        AuditEntry(
            project_id=project_id,
            actor_user_id=actor.id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            before=before,
            after=after,
            trace_id=trace_id_context.get(),
        )
    )
