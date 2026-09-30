"""Annotator assignment queue, draft, and submission routes, plus manager actions."""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from dada_api.api.deps import get_current_user, require_project_action
from dada_api.core import media_urls
from dada_api.db.session import get_session
from dada_api.models.batch import AnnotationAssignment, AssignmentStatus, BatchItem
from dada_api.models.media import Media
from dada_api.models.project import Project
from dada_api.models.user import User
from dada_api.schemas.assignment import (
    AssignmentDetail,
    AssignmentMedia,
    AssignmentQueueCounts,
    AssignmentQueueItem,
    AssignmentQueuePage,
    AssignmentReassign,
    BatchAssignment,
    BatchAssignmentPage,
    DocumentWrite,
    DraftSaved,
    QueueStateName,
    SubmissionReceived,
)
from dada_api.schemas.batch import BatchPurposeName
from dada_api.services import assignments
from dada_api.services.authorization import ProjectAction

router = APIRouter()


@router.get("/projects/{project_id}/assignments", response_model=AssignmentQueuePage)
async def list_my_assignments(
    purpose: BatchPurposeName | None = Query(default=None),
    state: QueueStateName | None = Query(default=None),
    cursor: str | None = Query(default=None),
    project: Project = Depends(require_project_action(ProjectAction.annotate)),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> AssignmentQueuePage:
    """List the caller's own image assignments.

    The queue never shows another annotator's work or progress, and an image
    stays in the queue however many peers are working on it.

    Args:
        purpose: Optional batch purpose filter.
        state: Optional assignment status filter.
        cursor: Opaque cursor from a previous page.
        project: Project resolved and authorized by the dependency.
        user: The annotator.
        session: Active database session.

    Returns:
        One page of assignments, the next cursor, and the caller's counts.
    """
    rows, next_cursor, counts = await assignments.list_queue(
        session, user, project, purpose, state, cursor
    )
    return AssignmentQueuePage(
        items=[
            AssignmentQueueItem(
                id=assignment.id,
                batch_id=batch.id,
                batch_purpose=batch.purpose,
                media_id=media.id,
                relative_path=media.relative_path,
                width=content.width,
                height=content.height,
                status=assignment.status,
                version=assignment.version,
                seeded_from_import=assignment.seed_document_id is not None,
                updated_at=assignment.updated_at,
            )
            for assignment, batch, media, content in rows
        ],
        next_cursor=next_cursor,
        counts=AssignmentQueueCounts(**counts),
    )


@router.get(
    "/projects/{project_id}/assignments/{assignment_id}",
    response_model=AssignmentDetail,
)
async def get_my_assignment(
    assignment_id: str,
    project: Project = Depends(require_project_action(ProjectAction.annotate)),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> AssignmentDetail:
    """Open one of the caller's assignments with its image and current work.

    Args:
        assignment_id: Assignment being opened.
        project: Project resolved and authorized by the dependency.
        user: The annotator.
        session: Active database session.

    Returns:
        The assignment, a signed link to its image, and its objects.
    """
    opened = await assignments.open_assignment(session, user, project, assignment_id)
    assignment, latest = opened.assignment, opened.latest
    objects = (
        latest.objects
        if assignment.status == AssignmentStatus.submitted and latest
        else assignment.draft or []
    )
    return AssignmentDetail(
        id=assignment.id,
        project_id=project.id,
        batch_id=opened.batch.id,
        batch_purpose=opened.batch.purpose,
        task_type=project.task_type,
        status=assignment.status,
        version=assignment.version,
        media=AssignmentMedia(
            id=opened.media.id,
            relative_path=opened.media.relative_path,
            width=opened.content.width,
            height=opened.content.height,
            image_url=media_urls.signed_media_url(opened.media.id, datetime.now(UTC)),
        ),
        objects=objects,
        seeded_from_import=assignment.seed_document_id is not None,
        draft_saved_at=assignment.draft_saved_at,
        revision=latest.revision if latest else None,
        submitted_at=latest.submitted_at if latest else None,
    )


@router.put(
    "/projects/{project_id}/assignments/{assignment_id}/draft",
    response_model=DraftSaved,
)
async def save_draft(
    assignment_id: str,
    request: DocumentWrite,
    project: Project = Depends(require_project_action(ProjectAction.annotate)),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> DraftSaved:
    """Save the caller's unfinished work on an assignment.

    Args:
        assignment_id: Assignment being saved.
        request: The complete draft and the version it was based on.
        project: Project resolved and authorized by the dependency.
        user: The annotator.
        session: Active database session.

    Returns:
        The assignment's new version.
    """
    saved = await assignments.save_draft(session, user, project, assignment_id, request)
    return DraftSaved(
        id=saved.id,
        status=saved.status,
        version=saved.version,
        draft_saved_at=saved.draft_saved_at,
    )


@router.post(
    "/projects/{project_id}/assignments/{assignment_id}/submit",
    response_model=SubmissionReceived,
)
async def submit_assignment(
    assignment_id: str,
    request: DocumentWrite,
    project: Project = Depends(require_project_action(ProjectAction.annotate)),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> SubmissionReceived:
    """Submit the caller's final document for an assignment.

    Send an ``Idempotency-Key`` so a retry after a lost response returns the
    original result instead of ``409 assignment_already_submitted``.

    Args:
        assignment_id: Assignment being submitted.
        request: The final document and the version it was based on.
        project: Project resolved and authorized by the dependency.
        user: The annotator.
        session: Active database session.

    Returns:
        The received submission and whether its image is now resolved.
    """
    assignment, submission, resolved = await assignments.submit(
        session, user, project, assignment_id, request
    )
    return SubmissionReceived(
        id=assignment.id,
        status=assignment.status,
        version=assignment.version,
        submission_id=submission.id,
        revision=submission.revision,
        submitted_at=submission.submitted_at,
        image_resolved=resolved,
    )


def _manager_view(
    assignment: AnnotationAssignment, item: BatchItem, media: Media
) -> BatchAssignment:
    """Build a manager's view of one assignment, without document content."""
    return BatchAssignment(
        id=assignment.id,
        batch_item_id=item.id,
        item_status=item.status,
        media_id=media.id,
        relative_path=media.relative_path,
        annotator_id=assignment.annotator_id,
        status=assignment.status,
        version=assignment.version,
        updated_at=assignment.updated_at,
    )


@router.get(
    "/projects/{project_id}/batches/{batch_id}/assignments",
    response_model=BatchAssignmentPage,
)
async def list_batch_assignments(
    batch_id: str,
    cursor: str | None = Query(default=None),
    project: Project = Depends(
        require_project_action(ProjectAction.manage_assignments)
    ),
    session: AsyncSession = Depends(get_session),
) -> BatchAssignmentPage:
    """List every assignment of a batch for a manager.

    Args:
        batch_id: Batch being inspected.
        cursor: Opaque cursor from a previous page.
        project: Project resolved and authorized by the dependency.
        session: Active database session.

    Returns:
        One page of assignments with the cursor for the next one.
    """
    rows, next_cursor = await assignments.list_batch_assignments(
        session, project, batch_id, cursor
    )
    return BatchAssignmentPage(
        items=[_manager_view(*row) for row in rows],
        next_cursor=next_cursor,
    )


@router.post(
    "/projects/{project_id}/assignments/{assignment_id}/reopen",
    response_model=BatchAssignment,
)
async def reopen_assignment(
    assignment_id: str,
    project: Project = Depends(
        require_project_action(ProjectAction.manage_assignments)
    ),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> BatchAssignment:
    """Give a submitted assignment back to its annotator for correction.

    Args:
        assignment_id: Submitted assignment.
        project: Project resolved and authorized by the dependency.
        user: Manager recorded as the actor.
        session: Active database session.

    Returns:
        The reopened assignment.
    """
    await assignments.reopen(session, user, project, assignment_id)
    return await _reload(session, project, assignment_id)


@router.post(
    "/projects/{project_id}/assignments/{assignment_id}/reassign",
    response_model=BatchAssignment,
    status_code=status.HTTP_201_CREATED,
)
async def reassign_assignment(
    assignment_id: str,
    request: AssignmentReassign,
    project: Project = Depends(
        require_project_action(ProjectAction.manage_assignments)
    ),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> BatchAssignment:
    """Move an image's work to another annotator.

    Args:
        assignment_id: Assignment being taken away.
        request: The member receiving the image.
        project: Project resolved and authorized by the dependency.
        user: Manager recorded as the actor.
        session: Active database session.

    Returns:
        The new assignment.
    """
    replacement = await assignments.reassign(
        session, user, project, assignment_id, str(request.annotator_id)
    )
    return await _reload(session, project, replacement.id)


@router.post(
    "/projects/{project_id}/batch-items/{item_id}/cancel",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def cancel_batch_item(
    item_id: str,
    project: Project = Depends(
        require_project_action(ProjectAction.manage_assignments)
    ),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> Response:
    """Withdraw an unresolved training image and return it to the pool.

    Args:
        item_id: Batch item being cancelled.
        project: Project resolved and authorized by the dependency.
        user: Manager recorded as the actor.
        session: Active database session.

    Returns:
        An empty response.
    """
    await assignments.cancel_item(session, user, project, item_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


async def _reload(
    session: AsyncSession, project: Project, assignment_id: str
) -> BatchAssignment:
    """Return a manager's view of an assignment after a change."""
    return _manager_view(
        *await assignments.manager_row(session, project, assignment_id)
    )
