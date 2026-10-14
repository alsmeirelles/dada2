"""Private candidate-review queues, recovery drafts, and submissions."""

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime

from pydantic import TypeAdapter, ValidationError
from sqlalchemy import func, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from dada_api.core.cursors import decode_cursor, encode_cursor
from dada_api.core.errors import ApiError, redact_validation_errors
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
from dada_api.models.project import Project, ProjectClass
from dada_api.models.user import User
from dada_api.schemas.review_assignment import (
    CandidateReviewEvidence,
    ImageReviewEvidence,
    ReviewEvidenceWrite,
)
from dada_api.services import annotation_documents, resolution_runs

PAGE_SIZE = 50
CANDIDATE_EVIDENCE = TypeAdapter(CandidateReviewEvidence)
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


def _invalid(errors: list[dict]) -> ApiError:
    """Return the 422 raised for evidence that breaks the review rules."""
    return ApiError(
        422,
        "invalid_review_evidence",
        "The review evidence does not fit this case.",
        details={"errors": errors},
    )


async def _validate_evidence(
    session: AsyncSession, project: Project, opened: OpenedReview, evidence: dict
) -> dict:
    """Check submitted evidence against its case's scope, classes, and image.

    Args:
        session: Active database session.
        project: Project of the case.
        opened: The review being submitted.
        evidence: Submitted evidence.

    Returns:
        The evidence in its canonical form.

    Raises:
        ApiError: 422 ``invalid_review_evidence``.
    """
    class_ids = set(
        await session.scalars(
            select(ProjectClass.id).where(ProjectClass.project_id == project.id)
        )
    )
    try:
        if opened.work_item.scope == "image":
            parsed = ImageReviewEvidence.model_validate(evidence)
            unknown = sorted(set(parsed.class_ids) - class_ids)
            if unknown or len(set(parsed.class_ids)) != len(parsed.class_ids):
                raise _invalid([{"field": "class_ids", "code": "unknown_class"}])
            return parsed.model_dump()
        parsed = CANDIDATE_EVIDENCE.validate_python(evidence)
    except ValidationError as error:
        raise _invalid(redact_validation_errors(error.errors())) from error

    canonical = parsed.model_dump()
    if canonical["decision"] == "object":
        errors = annotation_documents.validate_submission(
            project.task_type,
            [
                {
                    "id": "review",
                    "class_id": canonical["class_id"],
                    "geometry": canonical["geometry"],
                    "attributes": {},
                }
            ],
            class_ids,
            opened.content.width,
            opened.content.height,
        )
        if errors:
            raise _invalid([{"field": "geometry", "code": errors[0].code}])
    return canonical


async def submit(
    session: AsyncSession,
    user: User,
    project: Project,
    assignment_id: str,
    request: ReviewEvidenceWrite,
) -> tuple[ReviewAssignment, ReviewSubmission]:
    """Record a reviewer's immutable evidence and, with the case's last
    review, queue the second resolver round.

    Args:
        session: Active database session.
        user: The reviewer.
        project: Authorized project.
        assignment_id: Review assignment being submitted.
        request: Evidence and the version it was based on.

    Returns:
        The submitted assignment and its immutable submission.

    Raises:
        ApiError: 403 for another reviewer's assignment; 409 when stale or
            no longer active; 422 when the evidence breaks the review rules.
    """
    opened = await open_review(session, user, project, assignment_id, lock=True)
    assignment = opened.assignment
    _require_writable(assignment, request.version)
    evidence = await _validate_evidence(
        session, project, opened, dict(request.evidence)
    )
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
    await session.refresh(opened.work_item, with_for_update=True)
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
        await session.flush()
        await resolution_runs.on_review_ready(
            session, opened.work_item, datetime.now(UTC)
        )
    await session.commit()
    await session.refresh(assignment)
    await session.refresh(submission)
    return assignment, submission
