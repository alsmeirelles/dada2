"""Default annotation policy reads, versioned updates, and group validation."""

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from dada_api.core.errors import ApiError
from dada_api.models.annotation_policy import (
    AnnotationMode,
    AnnotationPolicyAnnotator,
    AnnotationPolicyDefault,
)
from dada_api.models.project import ANNOTATION_ROLES, Project, ProjectMember
from dada_api.models.user import User
from dada_api.schemas.annotation_policy import AnnotationPolicyUpdate
from dada_api.services import audit, resolvers

MINIMUM_CONSENSUS_GROUP = 2


async def get_policy(
    session: AsyncSession,
    project: Project,
) -> tuple[AnnotationPolicyDefault, list[str]]:
    """Return a project's default policy with its ordered group.

    Args:
        session: Active database session.
        project: Authorized project.

    Returns:
        The policy record and its annotator IDs in group order.

    Raises:
        ApiError: 404 when the project has no policy record.
    """
    policy = await session.scalar(
        select(AnnotationPolicyDefault).where(
            AnnotationPolicyDefault.project_id == project.id
        )
    )
    if policy is None:
        raise ApiError(404, "not_found", "The project has no annotation policy.")

    annotator_ids = list(
        await session.scalars(
            select(AnnotationPolicyAnnotator.user_id)
            .where(AnnotationPolicyAnnotator.policy_id == policy.id)
            .order_by(AnnotationPolicyAnnotator.position)
        )
    )
    return policy, annotator_ids


async def _validate_group(
    session: AsyncSession,
    project: Project,
    annotator_ids: list[str],
) -> None:
    """Reject a group that cannot annotate the project.

    Args:
        session: Active database session.
        project: Project the group belongs to.
        annotator_ids: Requested group, in order.

    Raises:
        ApiError: 422 when the group contains duplicates, non-members, or
            members whose role carries no annotation authority.
    """
    if len(set(annotator_ids)) != len(annotator_ids):
        raise ApiError(
            422,
            "invalid_consensus_group",
            "The group lists the same annotator more than once.",
        )

    roles = {
        user_id: role
        for user_id, role in await session.execute(
            select(ProjectMember.user_id, ProjectMember.role).where(
                ProjectMember.project_id == project.id,
                ProjectMember.user_id.in_(annotator_ids),
            )
        )
    }

    not_members = [user_id for user_id in annotator_ids if user_id not in roles]
    unauthorized = [
        user_id for user_id, role in roles.items() if role not in ANNOTATION_ROLES
    ]
    if not_members or unauthorized:
        raise ApiError(
            422,
            "invalid_consensus_group",
            "Every group member must be a project member allowed to annotate.",
            details={"not_members": not_members, "not_allowed": unauthorized},
        )


def _validate_resolver(
    project: Project, mode: AnnotationMode, resolver: str | None
) -> None:
    """Reject a resolver the project's task does not advertise.

    Args:
        project: Project the policy belongs to.
        mode: Requested annotation mode.
        resolver: Requested resolver identifier.

    Raises:
        ApiError: 422 when a resolver is missing, unexpected, or incompatible.
    """
    if mode is AnnotationMode.single:
        if resolver is not None:
            raise ApiError(
                422,
                "unsupported_resolver",
                "Single-annotation projects run no resolver.",
            )
        return

    if resolver is None:
        raise ApiError(
            422,
            "unsupported_resolver",
            "Consensus projects require a resolver.",
            details={
                "supported": list(resolvers.resolvers_for_task(project.task_type))
            },
        )
    if not resolvers.supports(project.task_type, resolver):
        raise ApiError(
            422,
            "unsupported_resolver",
            "That resolver is not advertised for this project's task.",
            details={
                "supported": list(resolvers.resolvers_for_task(project.task_type))
            },
        )


async def update_policy(
    session: AsyncSession,
    actor: User,
    project: Project,
    request: AnnotationPolicyUpdate,
) -> tuple[AnnotationPolicyDefault, list[str]]:
    """Replace a project's default policy, honouring its optimistic version.

    Args:
        session: Active database session.
        actor: User performing the change.
        project: Authorized project.
        request: Validated policy carrying the expected version.

    Returns:
        The updated policy and its annotator IDs in group order.

    Raises:
        ApiError: 409 on a stale version, 422 on an invalid group or resolver.
    """
    policy, previous_ids = await get_policy(session, project)
    if request.version != policy.version:
        raise ApiError(
            409,
            "version_conflict",
            "The annotation policy changed since it was read.",
            details={"expected_version": policy.version},
        )

    mode = AnnotationMode(request.mode)
    annotator_ids = [str(user_id) for user_id in request.annotator_ids]
    if (
        mode is AnnotationMode.consensus
        and len(annotator_ids) < MINIMUM_CONSENSUS_GROUP
    ):
        raise ApiError(
            422,
            "invalid_consensus_group",
            "Consensus annotation needs at least two distinct annotators.",
            details={"minimum": MINIMUM_CONSENSUS_GROUP},
        )
    if annotator_ids:
        await _validate_group(session, project, annotator_ids)
    _validate_resolver(project, mode, request.resolver)

    before = {
        "mode": policy.mode.value,
        "resolver": policy.resolver,
        "annotator_ids": previous_ids,
        "version": policy.version,
    }

    await session.execute(
        delete(AnnotationPolicyAnnotator).where(
            AnnotationPolicyAnnotator.policy_id == policy.id
        )
    )
    for position, user_id in enumerate(annotator_ids):
        session.add(
            AnnotationPolicyAnnotator(
                policy_id=policy.id, user_id=user_id, position=position
            )
        )

    policy.mode = mode
    policy.resolver = request.resolver
    policy.parameters = dict(request.parameters)
    policy.review_thresholds = dict(request.review_thresholds)
    policy.version += 1

    audit.record(
        session,
        actor,
        project.id,
        "annotation_policy.updated",
        "annotation_policy",
        policy.id,
        before=before,
        after={
            "mode": mode.value,
            "resolver": request.resolver,
            "annotator_ids": annotator_ids,
            "version": policy.version,
        },
    )
    await session.commit()
    await session.refresh(policy)
    return policy, annotator_ids
