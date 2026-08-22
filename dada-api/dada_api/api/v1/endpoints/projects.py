"""Project contract routes.

Project persistence and the remaining project operations belong to Phase 2. The
read route exists now because project-role authorization is enforced from
Phase 1 and must be provable over real HTTP requests.
"""

from fastapi import APIRouter, Depends, HTTPException, status

from dada_api.api.deps import require_project_action
from dada_api.models.project import Project
from dada_api.schemas.project import ProjectCreate, ProjectPage, ProjectResponse
from dada_api.services.authorization import ProjectAction

router = APIRouter()


@router.get("/projects", response_model=ProjectPage)
async def list_projects() -> ProjectPage:
    """Expose the future project-list contract.

    Raises:
        HTTPException: 501 until Phase 2 implements project persistence.
    """
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Project persistence is scheduled for Phase 2.",
    )


@router.post(
    "/projects", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED
)
async def create_project(_: ProjectCreate) -> ProjectResponse:
    """Expose the future project-create contract.

    Raises:
        HTTPException: 501 until Phase 2 implements project persistence.
    """
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Project persistence is scheduled for Phase 2.",
    )


@router.get("/projects/{project_id}", response_model=ProjectResponse)
async def read_project(
    project: Project = Depends(require_project_action(ProjectAction.read_project)),
) -> Project:
    """Return one project when the caller holds a role permitting reads.

    Args:
        project: Project resolved and authorized by the dependency.

    Returns:
        The authorized project.
    """
    return project
