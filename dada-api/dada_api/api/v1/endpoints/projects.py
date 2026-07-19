"""Phase 0 project contract placeholders.

Persistence and authorization are implemented in Phase 2. These operations are
registered now so generated OpenAPI types can be checked by the App.
"""

from fastapi import APIRouter, HTTPException, status

from dada_api.schemas.project import ProjectCreate, ProjectPage, ProjectResponse

router = APIRouter()


@router.get("/projects", response_model=ProjectPage)
async def list_projects() -> ProjectPage:
    """Expose the future project-list contract."""
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Project persistence is scheduled for Phase 2.",
    )


@router.post(
    "/projects", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED
)
async def create_project(_: ProjectCreate) -> ProjectResponse:
    """Expose the future project-create contract."""
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Project persistence is scheduled for Phase 2.",
    )
