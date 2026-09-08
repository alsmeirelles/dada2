"""Annotation batch listing, policy snapshot editing, and start routes."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from dada_api.api.deps import get_current_user, require_project_action
from dada_api.db.session import get_session
from dada_api.models.batch import AnnotationBatch
from dada_api.models.project import Project
from dada_api.models.user import User
from dada_api.schemas.batch import BatchPage, BatchPolicyUpdate, BatchResponse
from dada_api.services import batches as batch_service
from dada_api.services.authorization import ProjectAction

router = APIRouter()


async def _represent(
    session: AsyncSession,
    batch: AnnotationBatch,
) -> BatchResponse:
    """Build a batch response from its snapshot, group, and progress counts."""
    group = await batch_service.annotator_ids(session, batch)
    total_items, total_assignments, submitted = await batch_service.counts(
        session, batch
    )
    return BatchResponse(
        id=batch.id,
        project_id=batch.project_id,
        purpose=batch.purpose,
        status=batch.status,
        mode=batch.mode,
        annotator_ids=group,
        resolver=batch.resolver,
        resolver_version=batch.resolver_version,
        parameters=batch.parameters,
        review_thresholds=batch.review_thresholds,
        source_policy_version=batch.source_policy_version,
        selection_strategy=batch.selection_strategy,
        selection_seed=batch.selection_seed,
        selection_input_fingerprint=batch.selection_input_fingerprint,
        requested_size=batch.requested_size,
        total_items=total_items,
        total_assignments=total_assignments,
        submitted_assignments=submitted,
        started_at=batch.started_at,
        created_at=batch.created_at,
        updated_at=batch.updated_at,
    )


@router.get("/projects/{project_id}/batches", response_model=BatchPage)
async def list_batches(
    cursor: str | None = Query(default=None),
    project: Project = Depends(require_project_action(ProjectAction.read_project)),
    session: AsyncSession = Depends(get_session),
) -> BatchPage:
    """List a project's annotation batches.

    Args:
        cursor: Opaque cursor from a previous page.
        project: Project resolved and authorized by the dependency.
        session: Active database session.

    Returns:
        One page of batches with the cursor for the next one.
    """
    items, next_cursor = await batch_service.list_batches(session, project, cursor)
    return BatchPage(
        items=[await _represent(session, item) for item in items],
        next_cursor=next_cursor,
    )


@router.get("/projects/{project_id}/batches/{batch_id}", response_model=BatchResponse)
async def read_batch(
    batch_id: str,
    project: Project = Depends(require_project_action(ProjectAction.read_project)),
    session: AsyncSession = Depends(get_session),
) -> BatchResponse:
    """Return one batch with its policy snapshot and progress.

    Args:
        batch_id: Batch being read.
        project: Project resolved and authorized by the dependency.
        session: Active database session.

    Returns:
        The batch representation.
    """
    batch = await batch_service.get_batch(session, project, batch_id)
    return await _represent(session, batch)


@router.patch("/projects/{project_id}/batches/{batch_id}", response_model=BatchResponse)
async def update_batch_policy(
    batch_id: str,
    request: BatchPolicyUpdate,
    project: Project = Depends(
        require_project_action(ProjectAction.manage_annotation_policy)
    ),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> BatchResponse:
    """Replace a batch's policy snapshot while it is still preparing.

    Args:
        batch_id: Batch being changed.
        request: Validated replacement policy.
        project: Project resolved and authorized by the dependency.
        user: Authenticated user recorded as the actor.
        session: Active database session.

    Returns:
        The updated batch representation.
    """
    batch = await batch_service.get_batch(session, project, batch_id)
    updated = await batch_service.update_policy(session, user, project, batch, request)
    return await _represent(session, updated)


@router.post(
    "/projects/{project_id}/batches/{batch_id}/start", response_model=BatchResponse
)
async def start_batch(
    batch_id: str,
    project: Project = Depends(
        require_project_action(ProjectAction.manage_annotation_policy)
    ),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> BatchResponse:
    """Freeze a batch's policy and generate its assignments.

    Args:
        batch_id: Batch being started.
        project: Project resolved and authorized by the dependency.
        user: Authenticated user recorded as the actor.
        session: Active database session.

    Returns:
        The started batch representation.
    """
    batch = await batch_service.get_batch(session, project, batch_id)
    started = await batch_service.start(session, user, project, batch)
    return await _represent(session, started)
