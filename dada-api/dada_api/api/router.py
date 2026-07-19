"""Top-level API router."""

from fastapi import APIRouter

from dada_api.api.v1.router import router as v1_router
from dada_api.core.config import get_settings

router = APIRouter()
router.include_router(v1_router, prefix=get_settings().api_v1_prefix)
