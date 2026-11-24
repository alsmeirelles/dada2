"""Annotated-dataset export and project quality routes."""

from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from dada_api.api.deps import require_project_action
from dada_api.db.session import get_session
from dada_api.models.project import Project
from dada_api.schemas.quality import QualityReport
from dada_api.services import exports, quality
from dada_api.services.authorization import ProjectAction

router = APIRouter()


@router.get(
    "/projects/{project_id}/export",
    response_class=StreamingResponse,
    responses={200: {"content": {"application/zip": {}}}},
)
async def export_dataset(
    export_format: Literal["coco", "yolo", "csv"] | None = Query(
        default=None, alias="format"
    ),
    project: Project = Depends(require_project_action(ProjectAction.manage_learning)),
    session: AsyncSession = Depends(get_session),
) -> StreamingResponse:
    """Download the annotated dataset as a ZIP archive (D19).

    It holds only current accepted resolutions, split by training,
    validation, and test (or ``all`` for a static project), with the display
    copies of the images and ``provenance.json``. Detection and segmentation
    use ``coco`` (the default) or ``yolo``; classification uses ``csv``.

    Args:
        export_format: Label format; the task's default when omitted.
        project: Project authorized to manage learning.
        session: Active database session.

    Returns:
        The archive, streamed while it is written.
    """
    export = await exports.prepare(session, project, export_format, datetime.now(UTC))
    return StreamingResponse(
        exports.stream(export),
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{exports.file_name(export)}"'
        },
    )


@router.get("/projects/{project_id}/quality", response_model=QualityReport)
async def read_quality(
    project: Project = Depends(
        require_project_action(ProjectAction.read_annotator_performance)
    ),
    session: AsyncSession = Depends(get_session),
) -> QualityReport:
    """Return the project's review rate, resolution rate, and agreement.

    Args:
        project: Project authorized for performance reading.
        session: Active database session.

    Returns:
        The quality report, suppressed below the minimum sample.
    """
    items = await quality.collect(session, project)
    return QualityReport(**quality.report(project.task_type, items))
