"""Celery task that answers one assisted-annotation prompt."""

import logging
from typing import Any

from dada_api.active_learning import catalog
from dada_api.active_learning.contract import AdapterError, AssistanceRequest
from dada_api.workers.celery_app import ASSISTANCE_TASK, app

logger = logging.getLogger(__name__)


def run(payload: dict[str, Any]) -> dict[str, Any]:
    """Answer a prompt with the provider of the solution that retained the
    model.

    Args:
        payload: Serialized :class:`AssistanceRequest`.

    Returns:
        The serialized result, or ``{"failure": {"code", "detail"}}``.
    """
    request = AssistanceRequest.model_validate(payload)
    try:
        provider = catalog.load_assistant(
            request.model.solution_id, request.model.solution_version
        )
        return provider.suggest(request).model_dump(mode="json")
    except AdapterError as error:
        return {"failure": {"code": error.code, "detail": error.detail}}
    except Exception:
        logger.error(
            "assistance request %s failed unexpectedly",
            request.request_id,
            exc_info=True,
        )
        return {"failure": {"code": "assistance_failed", "detail": "unexpected error"}}


@app.task(name=ASSISTANCE_TASK, ignore_result=False)
def suggest(payload: dict[str, Any]) -> dict[str, Any]:
    """Celery entry point of ``assistance.suggest``.

    Args:
        payload: Serialized :class:`AssistanceRequest`.
    """
    return run(payload)
