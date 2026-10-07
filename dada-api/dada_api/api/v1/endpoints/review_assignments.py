"""Candidate-scoped review queue, recovery drafts, and submissions."""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from dada_api.api.deps import get_current_user, require_project_action
from dada_api.core import media_urls
from dada_api.db.session import get_session
from dada_api.models.consensus import ReviewAssignmentStatus
from dada_api.models.project import Project
from dada_api.models.user import User
from dada_api.schemas.assignment import AssignmentMedia, QueueStateName
from dada_api.schemas.review_assignment import (
    ReviewAssignmentDetail,
    ReviewDraftSaved,
    ReviewEvidenceWrite,
    ReviewQueueCounts,
    ReviewQueueItem,
    ReviewQueuePage,
    ReviewSubmissionReceived,
)
from dada_api.services import review_assignments
from dada_api.services.authorization import ProjectAction

router = APIRouter()


@router.get("/projects/{project_id}/review-assignments", response_model=ReviewQueuePage)
async def list_my_review_assignments(
    state: QueueStateName | None = Query(default=None),
    cursor: str | None = Query(default=None),
    project: Project = Depends(require_project_action(ProjectAction.annotate)),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> ReviewQueuePage:
    rows, next_cursor, counts = await review_assignments.list_queue(
        session, user, project, state, cursor
    )
    return ReviewQueuePage(
        items=[
            ReviewQueueItem(
                id=assignment.id,
                work_item_id=work_item.id,
                media_id=media.id,
                relative_path=media.relative_path,
                scope=work_item.scope,
                status=assignment.status,
                version=assignment.version,
                updated_at=assignment.updated_at,
            )
            for assignment, work_item, _, media, _ in rows
        ],
        next_cursor=next_cursor,
        counts=ReviewQueueCounts(**counts),
    )


@router.get(
    "/projects/{project_id}/review-assignments/{assignment_id}",
    response_model=ReviewAssignmentDetail,
)
async def get_my_review_assignment(
    assignment_id: str,
    project: Project = Depends(require_project_action(ProjectAction.annotate)),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> ReviewAssignmentDetail:
    opened = await review_assignments.open_review(session, user, project, assignment_id)
    assignment = opened.assignment
    evidence = (
        opened.submission.evidence
        if assignment.status == ReviewAssignmentStatus.submitted and opened.submission
        else assignment.draft or {}
    )
    return ReviewAssignmentDetail(
        id=assignment.id,
        project_id=project.id,
        work_item_id=opened.work_item.id,
        source_input_id=opened.source_input.id,
        candidate_key=opened.work_item.candidate_key,
        candidate_ordinal=opened.work_item.candidate_ordinal,
        scope=opened.work_item.scope,
        status=assignment.status,
        version=assignment.version,
        media=AssignmentMedia(
            id=opened.media.id,
            relative_path=opened.media.relative_path,
            width=opened.content.width,
            height=opened.content.height,
            image_url=media_urls.signed_media_url(opened.media.id, datetime.now(UTC)),
        ),
        candidate_context=opened.work_item.candidate_context,
        evidence=evidence,
        draft_saved_at=assignment.draft_saved_at,
        submitted_at=(opened.submission.submitted_at if opened.submission else None),
    )


@router.put(
    "/projects/{project_id}/review-assignments/{assignment_id}/draft",
    response_model=ReviewDraftSaved,
)
async def save_review_draft(
    assignment_id: str,
    request: ReviewEvidenceWrite,
    project: Project = Depends(require_project_action(ProjectAction.annotate)),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> ReviewDraftSaved:
    saved = await review_assignments.save_draft(
        session, user, project, assignment_id, request
    )
    return ReviewDraftSaved(
        id=saved.id,
        status=saved.status,
        version=saved.version,
        draft_saved_at=saved.draft_saved_at,
    )


@router.post(
    "/projects/{project_id}/review-assignments/{assignment_id}/submit",
    response_model=ReviewSubmissionReceived,
)
async def submit_review_assignment(
    assignment_id: str,
    request: ReviewEvidenceWrite,
    project: Project = Depends(require_project_action(ProjectAction.annotate)),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> ReviewSubmissionReceived:
    assignment, submission = await review_assignments.submit(
        session, user, project, assignment_id, request
    )
    return ReviewSubmissionReceived(
        id=assignment.id,
        status=assignment.status,
        version=assignment.version,
        submission_id=submission.id,
        submitted_at=submission.submitted_at,
    )
