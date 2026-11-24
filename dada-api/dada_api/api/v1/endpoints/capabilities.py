"""Runtime capability discovery endpoint."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from dada_api.active_learning import catalog as solutions
from dada_api.consensus import catalog
from dada_api.core.config import get_settings
from dada_api.db.session import get_session
from dada_api.schemas.capabilities import CapabilitiesResponse
from dada_api.services import resolution_runs

router = APIRouter()


@router.get("/capabilities", response_model=CapabilitiesResponse)
async def read_capabilities(
    session: AsyncSession = Depends(get_session),
) -> CapabilitiesResponse:
    """Return upload limits, media formats, tasks, resolvers, solutions, and
    transport.

    Resolver availability reflects the installed dependency versions and any
    open operator quarantine. Active-learning solutions are listed with the
    evaluation metrics each task allows.
    """
    settings = get_settings()
    return CapabilitiesResponse(
        supported_image_media_types=settings.image_media_types,
        max_file_bytes=settings.max_file_bytes,
        max_project_files=settings.max_project_files,
        upload_chunk_bytes=settings.upload_chunk_bytes,
        upload_session_ttl_hours=settings.upload_session_ttl_hours,
        max_import_file_bytes=settings.max_import_file_bytes,
        supported_task_types=["classification", "detection", "segmentation"],
        supported_annotation_modes=["single", "consensus"],
        consensus_pipelines=catalog.capabilities(
            quarantined=await resolution_runs.quarantined_keys(session)
        ),
        active_learning_solutions=solutions.capabilities(),
        evaluation_metrics={
            task: list(metrics) for task, metrics in solutions.METRICS.items()
        },
        realtime_transport=settings.realtime_transport,
    )
