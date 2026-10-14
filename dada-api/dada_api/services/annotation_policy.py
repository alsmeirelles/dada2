"""Default annotation policy reads, versioned updates, and group validation."""

from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from dada_api.consensus import catalog
from dada_api.core.errors import ApiError, redact_validation_errors
from dada_api.models.annotation_policy import (
    AnnotationMode,
    AnnotationPolicyAnnotator,
    AnnotationPolicyDefault,
)
from dada_api.models.audit import AuditEntry
from dada_api.models.batch import AnnotationBatch, BatchStatus
from dada_api.models.project import ANNOTATION_ROLES, Project, ProjectMember
from dada_api.models.user import User
from dada_api.schemas.annotation_policy import AnnotationPolicyUpdate
from dada_api.services import audit

MINIMUM_CONSENSUS_ANNOTATIONS = 2


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


@dataclass(frozen=True)
class ResolverConfiguration:
    """A validated resolver choice with every omitted value filled in.

    Attributes:
        resolver: Pipeline identifier, None in single mode.
        resolver_version: Pipeline version, None in single mode.
        parameters: Complete pipeline parameters.
        review_thresholds: Complete quality gates.
    """

    resolver: str | None
    resolver_version: str | None
    parameters: dict[str, Any]
    review_thresholds: dict[str, Any]


def _configure_resolver(
    project: Project,
    mode: AnnotationMode,
    resolver: str | None,
    parameters: dict[str, Any],
    review_thresholds: dict[str, Any],
) -> ResolverConfiguration:
    """Validate a resolver choice against the task's closed pipeline.

    Args:
        project: Project the policy belongs to.
        mode: Requested annotation mode.
        resolver: Requested pipeline identifier.
        parameters: Requested pipeline parameters.
        review_thresholds: Requested quality gates.

    Returns:
        The configuration to store.

    Raises:
        ApiError: 422 ``unsupported_resolver`` when the pipeline is missing,
            unexpected, or belongs to another task; 422
            ``invalid_resolver_configuration`` when a setting is unknown, out
            of bounds, or below the hard majority floor.
    """
    if mode is AnnotationMode.single:
        if resolver is not None:
            raise ApiError(
                422,
                "unsupported_resolver",
                "Single-annotation projects run no resolver.",
            )
        if parameters or review_thresholds:
            raise ApiError(
                422,
                "invalid_resolver_configuration",
                "Single-annotation projects take no resolver settings.",
            )
        return ResolverConfiguration(None, None, {}, {})

    pipeline = catalog.pipeline_for(project.task_type)
    if resolver != pipeline.id:
        raise ApiError(
            422,
            "unsupported_resolver",
            "Consensus projects require this task's resolver pipeline.",
            details={"supported": [pipeline.id]},
        )
    try:
        normalized_parameters, normalized_thresholds = catalog.normalize(
            project.task_type, parameters, review_thresholds
        )
    except ValidationError as error:
        raise ApiError(
            422,
            "invalid_resolver_configuration",
            "The resolver settings are not valid for this pipeline.",
            details={"errors": redact_validation_errors(error.errors())},
        ) from error
    return ResolverConfiguration(
        pipeline.id, pipeline.version, normalized_parameters, normalized_thresholds
    )


async def validate_policy(
    session: AsyncSession,
    project: Project,
    mode: AnnotationMode,
    annotator_ids: list[str],
    resolver: str | None,
    required_consensus_annotations: int | None,
    required_consensus_reviewers: int | None,
    parameters: dict[str, Any],
    review_thresholds: dict[str, Any],
) -> ResolverConfiguration:
    """Reject a policy a project cannot run and complete its resolver settings.

    Shared by the project default and by an annotation batch's snapshot, so a
    batch can never start under a group the default would have refused.

    Args:
        session: Active database session.
        project: Project the policy belongs to.
        mode: Requested annotation mode.
        annotator_ids: Requested group, in order.
        resolver: Requested pipeline identifier.
        required_consensus_annotations: Initial cohort size per image.
        required_consensus_reviewers: Reviewers per escalated candidate.
        parameters: Requested pipeline parameters.
        review_thresholds: Requested quality gates.

    Returns:
        The validated resolver configuration to store.

    Raises:
        ApiError: 422 when the group, the counts, or the resolver is invalid.
    """
    if annotator_ids:
        await _validate_group(session, project, annotator_ids)
    if mode is AnnotationMode.single and (
        required_consensus_annotations is not None
        or required_consensus_reviewers is not None
    ):
        raise ApiError(
            422,
            "invalid_consensus_counts",
            "Single annotation does not accept consensus counts.",
        )
    if mode is AnnotationMode.consensus:
        if (
            required_consensus_annotations is None
            or required_consensus_reviewers is None
        ):
            raise ApiError(
                422,
                "invalid_consensus_counts",
                "Consensus annotation requires initial and review counts.",
            )
        if required_consensus_annotations < MINIMUM_CONSENSUS_ANNOTATIONS:
            raise ApiError(
                422,
                "invalid_consensus_counts",
                "Consensus annotation needs at least two initial annotations.",
                details={"minimum": MINIMUM_CONSENSUS_ANNOTATIONS},
            )
        required_pool = required_consensus_annotations + required_consensus_reviewers
        if required_consensus_reviewers < 1 or required_pool > len(annotator_ids):
            raise ApiError(
                422,
                "invalid_consensus_counts",
                "The eligible pool must fit distinct initial and review cohorts.",
                details={
                    "required_pool_size": required_pool,
                    "pool_size": len(annotator_ids),
                },
            )
    return _configure_resolver(project, mode, resolver, parameters, review_thresholds)


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
    configuration = await validate_policy(
        session,
        project,
        mode,
        annotator_ids,
        request.resolver,
        request.required_consensus_annotations,
        request.required_consensus_reviewers,
        request.parameters,
        request.review_thresholds,
    )

    before = {
        "mode": policy.mode.value,
        "resolver": policy.resolver,
        "resolver_version": policy.resolver_version,
        "parameters": policy.parameters,
        "review_thresholds": policy.review_thresholds,
        "require_independent_adjudicator": policy.require_independent_adjudicator,
        "annotator_ids": previous_ids,
        "required_consensus_annotations": policy.required_consensus_annotations,
        "required_consensus_reviewers": policy.required_consensus_reviewers,
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
    policy.required_consensus_annotations = request.required_consensus_annotations
    policy.required_consensus_reviewers = request.required_consensus_reviewers
    policy.resolver = configuration.resolver
    policy.resolver_version = configuration.resolver_version
    policy.parameters = configuration.parameters
    policy.review_thresholds = configuration.review_thresholds
    policy.require_independent_adjudicator = request.require_independent_adjudicator
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
            "resolver": configuration.resolver,
            "resolver_version": configuration.resolver_version,
            "parameters": configuration.parameters,
            "review_thresholds": configuration.review_thresholds,
            "require_independent_adjudicator": request.require_independent_adjudicator,
            "annotator_ids": annotator_ids,
            "required_consensus_annotations": request.required_consensus_annotations,
            "required_consensus_reviewers": request.required_consensus_reviewers,
            "version": policy.version,
        },
    )
    await session.commit()
    await session.refresh(policy)
    return policy, annotator_ids


async def history(
    session: AsyncSession, project: Project
) -> tuple[list[tuple[AuditEntry, str | None]], int]:
    """Return a project's default-policy changes, newest first.

    The audit trail already records every change with its before and after
    states, so the history is read from it rather than stored twice.

    Args:
        session: Active database session.
        project: Authorized project.

    Returns:
        The policy audit entries with their actors' display names, and the
        number of batches still preparing.
    """
    entries = (
        await session.execute(
            select(AuditEntry, User.display_name)
            .outerjoin(User, User.id == AuditEntry.actor_user_id)
            .where(
                AuditEntry.project_id == project.id,
                AuditEntry.action == "annotation_policy.updated",
            )
            .order_by(AuditEntry.created_at.desc(), AuditEntry.id.desc())
        )
    ).all()
    preparing = await session.scalar(
        select(func.count())
        .select_from(AnnotationBatch)
        .where(
            AnnotationBatch.project_id == project.id,
            AnnotationBatch.status == BatchStatus.preparing,
        )
    )
    return [(entry, name) for entry, name in entries], preparing


def changed_fields(entry: AuditEntry) -> dict[str, dict[str, Any]]:
    """Return the fields an audited policy change altered.

    Args:
        entry: One ``annotation_policy.updated`` audit entry.

    Returns:
        Field name mapped to its ``before`` and ``after`` values.
    """
    before, after = entry.before or {}, entry.after or {}
    return {
        name: {"before": before.get(name), "after": after.get(name)}
        for name in sorted(set(before) | set(after))
        if name != "version" and before.get(name) != after.get(name)
    }
