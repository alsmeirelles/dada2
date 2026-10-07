"""Private candidate-review queues, recovery drafts, and submissions."""

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from dada_api.core.cursors import decode_cursor, encode_cursor
from dada_api.core.errors import ApiError
from dada_api.models.batch import AnnotationBatch, BatchItem
from dada_api.models.consensus import (
    ResolutionInput,
    ResolutionWorkItem,
    ResolutionWorkStatus,
    ReviewAssignment,
    ReviewAssignmentStatus,
    ReviewSubmission,
)
from dada_api.models.media import ContentObject, Media
from dada_api.models.project import Project
from dada_api.models.user import User
from dada_api.schemas.review_assignment import ReviewEvidenceWrite

PAGE_SIZE = 50
ACTIVE_STATUSES = (
    ReviewAssignmentStatus.pending,
    ReviewAssignmentStatus.in_progress,
    ReviewAssignmentStatus.submitted,
)


@dataclass(frozen=True)
class OpenedReview:
    assignment: ReviewAssignment
    work_item: ResolutionWorkItem
    source_input: ResolutionInput
    media: Media
    content: ContentObject
    submission: ReviewSubmission | None


def _content_hash(evidence: dict) -> str:
    value = json.dumps(evidence, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(value.encode()).hexdigest()


def _base_query(project: Project):
    return (
        select(
            ReviewAssignment,
            ResolutionWorkItem,
            ResolutionInput,
            Media,
            ContentObject,
        )
        .join(
            ResolutionWorkItem,
            ResolutionWorkItem.id == ReviewAssignment.work_item_id,
        )
        .join(
            ResolutionInput,
            ResolutionInput.id == ResolutionWorkItem.resolution_input_id,
        )
        .join(BatchItem, BatchItem.id == ResolutionWorkItem.batch_item_id)
        .join(AnnotationBatch, AnnotationBatch.id == BatchItem.batch_id)
        .join(Media, Media.id == BatchItem.media_id)
        .join(ContentObject, ContentObject.id == Media.content_object_id)
        .where(AnnotationBatch.project_id == project.id)
    )


async def list_queue(
    session: AsyncSession,
    user: User,
    project: Project,
    state: str | None,
    cursor: str | None,
) -> tuple[list[tuple], str | None, dict[str, int]]:
    order = (ReviewAssignment.created_at, ReviewAssignment.id)
    query = _base_query(project).where(
        ReviewAssignment.reviewer_id == user.id,
        ReviewAssignment.status.in_(ACTIVE_STATUSES),
    )
    if state is not None:
        query = query.where(ReviewAssignment.status == state)
    if cursor is not None:
        position = decode_cursor(cursor)
        query = query.where(
            tuple_(*order)
            > tuple_(datetime.fromisoformat(position["created_at"]), position["id"])
        )
    rows = [
        tuple(row)
        for row in await session.execute(query.order_by(*order).limit(PAGE_SIZE + 1))
    ]
    next_cursor = None
    if len(rows) > PAGE_SIZE:
        rows = rows[:PAGE_SIZE]
        assignment = rows[-1][0]
        next_cursor = encode_cursor(
            {"created_at": assignment.created_at.isoformat(), "id": assignment.id}
        )

    counts = dict(
        (
            await session.execute(
                select(ReviewAssignment.status, func.count())
                .join(
                    ResolutionWorkItem,
                    ResolutionWorkItem.id == ReviewAssignment.work_item_id,
                )
                .join(BatchItem, BatchItem.id == ResolutionWorkItem.batch_item_id)
                .join(AnnotationBatch, AnnotationBatch.id == BatchItem.batch_id)
                .where(
                    AnnotationBatch.project_id == project.id,
                    ReviewAssignment.reviewer_id == user.id,
                )
                .group_by(ReviewAssignment.status)
            )
        ).all()
    )
    return (
        rows,
        next_cursor,
        {status: counts.get(status, 0) for status in ACTIVE_STATUSES},
    )


async def open_review(
    session: AsyncSession,
    user: User,
    project: Project,
    assignment_id: str,
    *,
    lock: bool = False,
) -> OpenedReview:
    query = _base_query(project).where(ReviewAssignment.id == assignment_id)
    if lock:
        query = query.with_for_update(of=ReviewAssignment)
    row = (await session.execute(query)).first()
    if row is None:
        raise ApiError(404, "not_found", "The review assignment does not exist.")
    assignment, work_item, source_input, media, content = row
    if assignment.reviewer_id != user.id:
        raise ApiError(
            403,
            "review_assignment_not_owned",
            "The review assignment belongs to another reviewer.",
        )
    submission = await session.scalar(
        select(ReviewSubmission).where(
            ReviewSubmission.review_assignment_id == assignment.id
        )
    )
    return OpenedReview(assignment, work_item, source_input, media, content, submission)


def _require_writable(assignment: ReviewAssignment, version: int) -> None:
    if assignment.status == ReviewAssignmentStatus.submitted:
        raise ApiError(
            409, "review_already_submitted", "The review is already submitted."
        )
    if assignment.status not in (
        ReviewAssignmentStatus.pending,
        ReviewAssignmentStatus.in_progress,
    ):
        raise ApiError(409, "review_not_active", "The review is no longer active.")
    if assignment.version != version:
        raise ApiError(
            409,
            "version_conflict",
            "The review changed since it was read.",
            details={"expected_version": assignment.version},
        )


async def save_draft(
    session: AsyncSession,
    user: User,
    project: Project,
    assignment_id: str,
    request: ReviewEvidenceWrite,
) -> ReviewAssignment:
    opened = await open_review(session, user, project, assignment_id, lock=True)
    assignment = opened.assignment
    _require_writable(assignment, request.version)
    assignment.draft = dict(request.evidence)
    assignment.draft_saved_at = datetime.now(UTC)
    assignment.status = ReviewAssignmentStatus.in_progress
    assignment.version += 1
    await session.commit()
    await session.refresh(assignment)
    return assignment


async def submit(
    session: AsyncSession,
    user: User,
    project: Project,
    assignment_id: str,
    request: ReviewEvidenceWrite,
) -> tuple[ReviewAssignment, ReviewSubmission]:
    opened = await open_review(session, user, project, assignment_id, lock=True)
    assignment = opened.assignment
    _require_writable(assignment, request.version)
    evidence = dict(request.evidence)
    submission = ReviewSubmission(
        review_assignment_id=assignment.id,
        work_item_id=opened.work_item.id,
        source_input_id=opened.source_input.id,
        reviewer_id=user.id,
        evidence=evidence,
        content_hash=_content_hash(evidence),
    )
    session.add(submission)
    assignment.draft = None
    assignment.status = ReviewAssignmentStatus.submitted
    assignment.version += 1
    await session.flush()
    remaining = await session.scalar(
        select(func.count())
        .select_from(ReviewAssignment)
        .where(
            ReviewAssignment.work_item_id == opened.work_item.id,
            ReviewAssignment.status != ReviewAssignmentStatus.submitted,
        )
    )
    if not remaining:
        opened.work_item.status = ResolutionWorkStatus.review_ready
    await session.commit()
    await session.refresh(assignment)
    await session.refresh(submission)
    return assignment, submission
