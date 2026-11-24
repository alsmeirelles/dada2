"""Assisted annotation with a project's retained target model (D18).

A prompt is answered only for the annotator who owns an open assignment of a
detection or segmentation project. The suggestion comes from the last target
model the project's solution evaluated, runs on the ``assistance`` queue, and
is never stored: a timeout or failure leaves the draft exactly as it was.
"""

from collections.abc import Awaitable, Callable
from uuid import uuid4

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dada_api.active_learning import catalog
from dada_api.active_learning.contract import (
    AdapterError,
    AssistanceRequest,
    AssistanceResult,
    Prompt,
    read_assistance_model,
)
from dada_api.core.config import get_settings
from dada_api.core.errors import ApiError
from dada_api.models.project import ProjectClass
from dada_api.models.user import User
from dada_api.schemas.inference import SamPredictRequest, SamPredictResponse
from dada_api.services import annotation_documents, assignments, storage
from dada_api.services.authorization import ProjectAction, authorize_project_action
from dada_api.services.learning_runs import OBJECT_TASKS, assistance_folder

Dispatcher = Callable[[AssistanceRequest, float], Awaitable[dict]]


def _unavailable(reason: str) -> ApiError:
    """Return the error of a project that cannot be assisted right now."""
    return ApiError(
        409,
        "assistance_unavailable",
        "Assisted annotation is not available for this project yet.",
        details={"reason": reason},
    )


def _prompt(raw: dict, width: int, height: int) -> Prompt:
    """Validate a prompt against the canonical image plane.

    Raises:
        ApiError: 422 ``invalid_prompt`` for a point outside the image or a
            box that is empty or leaves it.
    """
    prompt = Prompt(type=raw["type"], coordinates=raw["coordinates"])
    values = prompt.coordinates
    if prompt.type == "point":
        valid = (
            len(values) == 2 and 0 <= values[0] <= width and 0 <= values[1] <= height
        )
    else:
        valid = len(values) == 4 and (
            annotation_documents.geometry_error(
                "detection", {"type": "rectangle", "coordinates": values}, width, height
            )
            is None
        )
    if not valid:
        raise ApiError(
            422,
            "invalid_prompt",
            "The prompt must lie inside the image.",
            details={"type": prompt.type},
        )
    return prompt


async def suggest(
    session: AsyncSession,
    user: User,
    request: SamPredictRequest,
    dispatch: Dispatcher,
) -> SamPredictResponse:
    """Answer one prompt with the project's retained target model.

    Args:
        session: Active database session.
        user: The annotator asking.
        request: The prompt and the assignment it belongs to.
        dispatch: Sends the request to the assistance worker and returns its
            raw answer, raising ``TimeoutError`` when none arrives in time.

    Returns:
        The suggestion, or ``no_suggestion``.

    Raises:
        ApiError: 403 or 404 when the caller may not work on the assignment;
            409 when it is closed or no compatible target model exists; 422
            for an unsupported task or an invalid prompt; 503 when the worker
            times out or fails.
    """
    project = await authorize_project_action(
        session, user, str(request.project_id), ProjectAction.annotate
    )
    _, _, content = await assignments.open_work(
        session, user, project, str(request.assignment_id)
    )
    if project.task_type not in OBJECT_TASKS:
        raise ApiError(
            422,
            "assistance_not_supported",
            "Assisted annotation applies to detection and segmentation.",
            details={"task_type": project.task_type},
        )
    prompt = _prompt(request.prompts[0].model_dump(), content.width, content.height)

    folder = storage.media_path(assistance_folder(project.id))
    model = read_assistance_model(str(folder))
    if model is None:
        raise _unavailable("no_target_model")
    class_ids = list(
        await session.scalars(
            select(ProjectClass.id)
            .where(ProjectClass.project_id == project.id)
            .order_by(ProjectClass.display_order)
        )
    )
    if model.task != project.task_type or model.class_ids != class_ids:
        raise _unavailable("incompatible_target_model")
    try:
        solution = catalog.runnable(model.solution_id, model.solution_version)
    except AdapterError as error:
        raise _unavailable("solution_unavailable") from error
    if solution.assistant is None:
        raise _unavailable("solution_unavailable")

    request_id = request.request_id or str(uuid4())
    image = storage.media_path(
        storage.display_key(
            project.id, content.sha256, content.media_type, content.storage_key
        )
    )
    try:
        payload = await dispatch(
            AssistanceRequest(
                request_id=request_id,
                task=project.task_type,
                image_path=str(image),
                width=content.width,
                height=content.height,
                prompt=prompt,
                model_dir=str(folder),
                model=model,
            ),
            get_settings().assistance_timeout_seconds,
        )
    except TimeoutError as error:
        raise ApiError(
            503,
            "assistance_timeout",
            "The model did not answer in time; the draft is unchanged.",
            headers={"Retry-After": "5"},
        ) from error
    if "failure" in payload:
        raise ApiError(
            503,
            "assistance_failed",
            "The model could not answer; the draft is unchanged.",
            details={"code": payload["failure"]["code"]},
        )
    try:
        result = AssistanceResult.model_validate(payload)
        response = SamPredictResponse(
            request_id=request_id,
            assignment_id=request.assignment_id,
            status=result.status,
            geometry=result.geometry,
            score=result.score,
            model=result.model,
        )
    except ValidationError as error:
        raise ApiError(
            503,
            "assistance_failed",
            "The model could not answer; the draft is unchanged.",
            details={"code": "invalid_suggestion"},
        ) from error
    geometry = response.geometry.model_dump() if response.geometry else None
    if (result.status == "suggestion") != (geometry is not None) or (
        geometry is not None
        and annotation_documents.geometry_error(
            project.task_type, geometry, content.width, content.height
        )
        is not None
    ):
        raise ApiError(
            503,
            "assistance_failed",
            "The model could not answer; the draft is unchanged.",
            details={"code": "invalid_suggestion"},
        )
    return response
