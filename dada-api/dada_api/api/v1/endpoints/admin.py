"""Admin-only operational endpoints."""

from fastapi import APIRouter, Depends

from dada_api.api.deps import RequireAdmin
from dada_api.models.user import User

router = APIRouter()


@router.get("/status")
async def read_admin_status(_: User = Depends(RequireAdmin)) -> dict[str, str]:
    """Return an admin-only operational status response."""
    return {"status": "ok", "scope": "admin"}
