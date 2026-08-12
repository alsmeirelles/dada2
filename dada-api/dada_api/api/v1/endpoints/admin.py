"""Administrator-only operational endpoints."""

from fastapi import APIRouter, Depends

from dada_api.api.deps import require_administrator
from dada_api.models.user import User

router = APIRouter()


@router.get("/status")
async def read_admin_status(_: User = Depends(require_administrator)) -> dict[str, str]:
    """Return an administrator-only operational status response.

    Args:
        _: Authenticated administrator.

    Returns:
        A static status payload confirming administrator authority.
    """
    return {"status": "ok", "scope": "admin"}
