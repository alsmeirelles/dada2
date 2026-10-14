"""Default annotation policy routes."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from dada_api.api.deps import get_current_user, require_project_action
from dada_api.db.session import get_session
from dada_api.models.annotation_policy import AnnotationPolicyDefault
from dada_api.models.project import Project
from dada_api.models.user import User
from dada_api.schemas.annotation_policy import (
    AnnotationPolicyResponse,
    AnnotationPolicyUpdate,
    PolicyChange,
    PolicyHistory,
)
from dada_api.services import annotation_policy as policy_service
from dada_api.services.authorization import ProjectAction

router = APIRouter()


def _response(
    policy: AnnotationPolicyDefault, annotator_ids: list[str]
) -> AnnotationPolicyResponse:
    """Build the policy representation the App consumes.

    Args:
        policy: Stored policy record.
        annotator_ids: Group members in order.

    Returns:
        The policy representation.
    """
    return AnnotationPolicyResponse(
        mode=policy.mode.value,
        annotator_ids=annotator_ids,
        required_consensus_annotations=policy.required_consensus_annotations,
        required_consensus_reviewers=policy.required_consensus_reviewers,
        resolver=policy.resolver,
        resolver_version=policy.resolver_version,
        parameters=policy.parameters,
        review_thresholds=policy.review_thresholds,
        require_independent_adjudicator=policy.require_independent_adjudicator,
        version=policy.version,
    )


@router.get(
    "/projects/{project_id}/annotation-policy",
    response_model=AnnotationPolicyResponse,
)
async def read_annotation_policy(
    project: Project = Depends(require_project_action(ProjectAction.read_project)),
    session: AsyncSession = Depends(get_session),
) -> AnnotationPolicyResponse:
    """Return a project's default annotation policy.

    Args:
        project: Project resolved and authorized by the dependency.
        session: Active database session.

    Returns:
        The current policy and its ordered group.
    """
    policy, annotator_ids = await policy_service.get_policy(session, project)
    return _response(policy, annotator_ids)


@router.put(
    "/projects/{project_id}/annotation-policy",
    response_model=AnnotationPolicyResponse,
)
async def update_annotation_policy(
    request: AnnotationPolicyUpdate,
    actor: User = Depends(get_current_user),
    project: Project = Depends(
        require_project_action(ProjectAction.manage_annotation_policy)
    ),
    session: AsyncSession = Depends(get_session),
) -> AnnotationPolicyResponse:
    """Replace a project's default annotation policy.

    Args:
        request: Validated policy carrying the expected version.
        actor: Authenticated user performing the change.
        project: Project resolved and authorized by the dependency.
        session: Active database session.

    Returns:
        The updated policy and its ordered group.
    """
    policy, annotator_ids = await policy_service.update_policy(
        session, actor, project, request
    )
    return _response(policy, annotator_ids)


@router.get(
    "/projects/{project_id}/annotation-policy/history",
    response_model=PolicyHistory,
)
async def read_annotation_policy_history(
    project: Project = Depends(
        require_project_action(ProjectAction.manage_annotation_policy)
    ),
    session: AsyncSession = Depends(get_session),
) -> PolicyHistory:
    """Return the read-only history of the default policy, newest first.

    Args:
        project: Project resolved and authorized by the dependency.
        session: Active database session.

    Returns:
        Every change with its actor, time, and changed fields.
    """
    entries, preparing = await policy_service.history(session, project)
    return PolicyHistory(
        items=[
            PolicyChange(
                version=(entry.after or {}).get("version", 0),
                actor_id=entry.actor_user_id,
                actor_name=name,
                changed_at=entry.created_at,
                resolver=(entry.after or {}).get("resolver"),
                resolver_version=(entry.after or {}).get("resolver_version"),
                changed_fields=policy_service.changed_fields(entry),
            )
            for entry, name in entries
        ],
        preparing_batches=preparing,
    )
