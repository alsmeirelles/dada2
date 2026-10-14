"""Manager resolution queue, evidence, retry, adjudication, lease, and run routes."""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dada_api.api.deps import get_current_user, require_project_action
from dada_api.db.session import get_session
from dada_api.models.consensus import ResolutionInput
from dada_api.models.project import Project
from dada_api.models.user import User
from dada_api.schemas.resolution import (
    AdjudicationRequest,
    AdjudicationResponse,
    CancelRunRequest,
    EvidenceResponse,
    LeaseResponse,
    LeaseRevokeRequest,
    PerformanceReport,
    PerformanceSummary,
    ResolutionQueueItem,
    ResolutionQueuePage,
    ResolverEligibility,
    RetryRequest,
    RunView,
    StrategyEligibility,
    WorkItemStatusName,
)
from dada_api.services import (
    annotation_policy,
    calibration_snapshots,
    performance,
    resolution_leases,
    resolutions,
)
from dada_api.services.authorization import ProjectAction

router = APIRouter()


def _now() -> datetime:
    """Return the current UTC time."""
    return datetime.now(UTC)


@router.get(
    "/projects/{project_id}/batches/{batch_id}/resolutions",
    response_model=ResolutionQueuePage,
)
async def list_resolution_queue(
    batch_id: str,
    state: list[WorkItemStatusName] = Query(default=["review_required"]),
    reason: str | None = Query(default=None, max_length=32),
    class_strategy: str | None = Query(default=None, max_length=64),
    min_age_seconds: int | None = Query(default=None, ge=0),
    cursor: str | None = Query(default=None),
    project: Project = Depends(
        require_project_action(ProjectAction.read_annotation_evidence)
    ),
    session: AsyncSession = Depends(get_session),
) -> ResolutionQueuePage:
    """List a batch's open resolution cases, failures first.

    Args:
        batch_id: Batch whose cases are listed.
        state: Work item statuses to include; defaults to cases awaiting an
            expert.
        reason: Optional reason filter.
        class_strategy: Optional class-strategy filter.
        min_age_seconds: Only cases at least this old.
        cursor: Opaque page cursor.
        project: Project authorized for evidence reading.
        session: Active database session.

    Returns:
        One page of cases without document content.
    """
    now = _now()
    rows, next_cursor = await resolutions.list_queue(
        session,
        project,
        batch_id,
        states=list(state),
        reason=reason,
        strategy=class_strategy,
        min_age_seconds=min_age_seconds,
        cursor=cursor,
        now=now,
    )
    items = []
    for work_item, item, media, run in rows:
        submitted, required = await resolutions.review_counts(session, work_item.id)
        candidate = resolutions.candidate_of(
            await resolutions.proposal_of(session, work_item.run_id),
            work_item.candidate_key,
        )
        lease = await resolution_leases.active_lease(session, work_item.id, now)
        source_input = await session.get(ResolutionInput, work_item.resolution_input_id)
        items.append(
            ResolutionQueueItem(
                work_item_id=work_item.id,
                batch_item_id=item.id,
                media_id=media.id,
                relative_path=media.relative_path,
                scope=work_item.scope,
                candidate_key=work_item.candidate_key,
                status=work_item.status,
                reason=work_item.reason,
                submissions=sum(
                    1
                    for entry in source_input.source_inputs
                    if entry.get("kind", "submission") == "submission"
                ),
                reviews_submitted=submitted,
                reviews_required=required,
                resolver=run.pipeline if run is not None else None,
                resolver_version=run.pipeline_version if run is not None else None,
                class_strategy=(
                    run.configuration["parameters"]["class_strategy"]["strategy"]
                    if run is not None
                    else None
                ),
                metrics=candidate["metrics"] if candidate is not None else {},
                lease_holder_id=lease.holder_id if lease is not None else None,
                lease_expires_at=lease.expires_at if lease is not None else None,
                created_at=work_item.created_at,
            )
        )
    return ResolutionQueuePage(items=items, next_cursor=next_cursor)


@router.get(
    "/projects/{project_id}/batch-items/{item_id}/evidence",
    response_model=EvidenceResponse,
)
async def read_evidence(
    item_id: str,
    project: Project = Depends(
        require_project_action(ProjectAction.read_annotation_evidence)
    ),
    session: AsyncSession = Depends(get_session),
) -> EvidenceResponse:
    """Return one image's complete, named evidence and resolution history.

    Args:
        item_id: Batch item of the image.
        project: Project authorized for evidence reading.
        session: Active database session.

    Returns:
        The image's evidence, cases, runs, and expected versions.
    """
    return await resolutions.evidence(session, project, item_id, _now())


@router.post(
    "/projects/{project_id}/batch-items/{item_id}/resolve",
    response_model=RunView,
    status_code=status.HTTP_202_ACCEPTED,
)
async def retry_resolution(
    item_id: str,
    request: RetryRequest,
    project: Project = Depends(require_project_action(ProjectAction.run_resolution)),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> RunView:
    """Queue a manual resolver run over an image's latest evidence.

    Args:
        item_id: Batch item of the image.
        request: Expected versions, rationale, optional configuration.
        project: Project authorized to run resolution.
        user: Owner or manager recorded as the actor.
        session: Active database session.

    Returns:
        The queued run.
    """
    run = await resolutions.retry(session, user, project, item_id, request, _now())
    return resolutions.run_view(run, None)


@router.post(
    "/projects/{project_id}/resolution-runs/{run_id}/cancel",
    response_model=RunView,
)
async def cancel_resolution_run(
    run_id: str,
    request: CancelRunRequest,
    project: Project = Depends(require_project_action(ProjectAction.run_resolution)),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> RunView:
    """Cancel an active run; the image moves to an expert.

    Args:
        run_id: Run to cancel.
        request: Mandatory rationale.
        project: Project authorized to run resolution.
        user: Owner or manager recorded as the actor.
        session: Active database session.

    Returns:
        The cancelled, or cancellation-flagged, run.
    """
    run = await resolutions.cancel_run(session, user, project, run_id, request, _now())
    return resolutions.run_view(run, None)


@router.post(
    "/projects/{project_id}/resolution-work-items/{work_item_id}/adjudicate",
    response_model=AdjudicationResponse,
)
async def adjudicate_work_item(
    work_item_id: str,
    request: AdjudicationRequest,
    project: Project = Depends(require_project_action(ProjectAction.adjudicate)),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> AdjudicationResponse:
    """Accept, edit, or replace the decision of one resolution case.

    Args:
        work_item_id: Case being decided.
        request: Action, objects, rationale, and expected versions.
        project: Project authorized for adjudication.
        user: Owner or manager recorded as the adjudicator.
        session: Active database session.

    Returns:
        The decision and, when the image closed, its new resolution.
    """
    adjudication, resolution = await resolutions.adjudicate(
        session, user, project, work_item_id, request, _now()
    )
    return AdjudicationResponse(
        adjudication=resolutions.adjudication_view(adjudication),
        resolution=(
            resolutions.resolution_view(resolution) if resolution is not None else None
        ),
    )


@router.post(
    "/projects/{project_id}/resolution-work-items/{work_item_id}/lease",
    response_model=LeaseResponse,
)
async def acquire_lease(
    work_item_id: str,
    project: Project = Depends(require_project_action(ProjectAction.adjudicate)),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> LeaseResponse:
    """Acquire or renew the caller's 15-minute edit lease on a case.

    Args:
        work_item_id: Case to edit.
        project: Project authorized for adjudication.
        user: Owner or manager taking the lease.
        session: Active database session.

    Returns:
        The caller's active lease.
    """
    lease = await resolution_leases.acquire(
        session, user, project, work_item_id, _now()
    )
    return resolutions.lease_view(lease)


@router.delete(
    "/projects/{project_id}/resolution-work-items/{work_item_id}/lease",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def release_lease(
    work_item_id: str,
    project: Project = Depends(require_project_action(ProjectAction.adjudicate)),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> Response:
    """Release the caller's edit lease on a case.

    Args:
        work_item_id: Case being left.
        project: Project authorized for adjudication.
        user: Lease holder.
        session: Active database session.

    Returns:
        An empty response.
    """
    await resolution_leases.release(session, user, project, work_item_id, _now())
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/projects/{project_id}/resolution-work-items/{work_item_id}/lease/revoke",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def revoke_lease(
    work_item_id: str,
    request: LeaseRevokeRequest,
    project: Project = Depends(require_project_action(ProjectAction.adjudicate)),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> Response:
    """Revoke an abandoned edit lease with an audited reason.

    Args:
        work_item_id: Case whose lease is revoked.
        request: Mandatory reason.
        project: Project authorized for adjudication.
        user: Owner or manager revoking.
        session: Active database session.

    Returns:
        An empty response.
    """
    await resolution_leases.revoke(
        session, user, project, work_item_id, request.reason, _now()
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/projects/{project_id}/annotator-performance",
    response_model=PerformanceReport,
)
async def read_annotator_performance(
    project: Project = Depends(
        require_project_action(ProjectAction.read_annotator_performance)
    ),
    session: AsyncSession = Depends(get_session),
) -> PerformanceReport:
    """Return named, suppressed aggregates of the project's observations.

    Args:
        project: Project authorized for performance reading.
        session: Active database session.

    Returns:
        One summary per annotator and evaluation source.
    """
    summaries = performance.summarize(
        await performance.current_observations(session, project.id)
    )
    names = {
        user.id: user.display_name
        for user in await session.scalars(
            select(User).where(
                User.id.in_([entry["annotator_id"] for entry in summaries])
            )
        )
    }
    return PerformanceReport(
        items=[
            PerformanceSummary(**entry, annotator_name=names[entry["annotator_id"]])
            for entry in summaries
        ],
        minimum_decisions=performance.MINIMUM_DECISIONS,
        minimum_cell=performance.MINIMUM_CELL,
    )


@router.get(
    "/projects/{project_id}/resolver-eligibility",
    response_model=ResolverEligibility,
)
async def read_resolver_eligibility(
    project: Project = Depends(
        require_project_action(ProjectAction.manage_annotation_policy)
    ),
    session: AsyncSession = Depends(get_session),
) -> ResolverEligibility:
    """Report what each conditional strategy still lacks for this project.

    Args:
        project: Project authorized to manage its annotation policy.
        session: Active database session.

    Returns:
        One verdict per conditional strategy over the default policy's pool.
    """
    _, pool = await annotation_policy.get_policy(session, project)
    return ResolverEligibility(
        strategies=[
            StrategyEligibility(
                strategy=built.strategy,
                eligible=built.eligible,
                missing=built.missing,
                report=built.report,
            )
            for built in await calibration_snapshots.eligibility(session, project, pool)
        ]
    )
