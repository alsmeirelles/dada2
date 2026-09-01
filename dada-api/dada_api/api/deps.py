"""FastAPI dependencies for authentication and authorization."""

from collections.abc import Callable, Coroutine
from typing import Any

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from dada_api.core.errors import ApiError
from dada_api.core.security import decode_access_token
from dada_api.db.session import get_session
from dada_api.models.project import Project
from dada_api.models.upload import UploadSession
from dada_api.models.user import User
from dada_api.services.authorization import ProjectAction, authorize_project_action
from dada_api.services.users import get_user_by_username

bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    session: AsyncSession = Depends(get_session),
) -> User:
    """Resolve the authenticated user from the bearer token.

    Args:
        credentials: Bearer credentials supplied by the client.
        session: Active database session.

    Returns:
        The authenticated, active user.

    Raises:
        HTTPException: 401 when credentials are missing, invalid, or belong to
            an unknown or deactivated user.
    """
    unauthorized_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication credentials were not provided or are invalid.",
        headers={"WWW-Authenticate": "Bearer"},
    )

    if credentials is None or credentials.scheme.lower() != "bearer":
        raise unauthorized_error

    try:
        payload = decode_access_token(credentials.credentials)
    except ValueError as error:
        raise unauthorized_error from error

    user = await get_user_by_username(session, str(payload["sub"]))
    if user is None or not user.is_active:
        raise unauthorized_error

    return user


async def require_administrator(user: User = Depends(get_current_user)) -> User:
    """Return the current user when they hold global administrator authority.

    Args:
        user: Authenticated user.

    Returns:
        The authenticated administrator.

    Raises:
        HTTPException: 403 when the user is not a global administrator.
    """
    if not user.is_administrator:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="The authenticated user is not allowed to perform this action.",
        )
    return user


def require_project_action(
    action: ProjectAction,
) -> Callable[..., Coroutine[Any, Any, Project]]:
    """Build a dependency authorizing one project-scoped action.

    Args:
        action: Operation the route performs.

    Returns:
        A dependency returning the authorized project.
    """

    async def dependency(
        project_id: str,
        user: User = Depends(get_current_user),
        session: AsyncSession = Depends(get_session),
    ) -> Project:
        """Return the project when the caller may perform the action."""
        return await authorize_project_action(session, user, project_id, action)

    return dependency


def require_upload_action(
    action: ProjectAction,
) -> Callable[..., Coroutine[Any, Any, UploadSession]]:
    """Build a dependency authorizing an action through an upload's project.

    Upload routes are addressed by session rather than by project, so the
    project is resolved from the session before the same central matrix decides
    the caller's authority.

    Args:
        action: Operation the route performs.

    Returns:
        A dependency returning the authorized upload session.
    """

    async def dependency(
        upload_id: str,
        user: User = Depends(get_current_user),
        session: AsyncSession = Depends(get_session),
    ) -> UploadSession:
        """Return the upload session when the caller may perform the action."""
        upload = await session.get(UploadSession, upload_id)
        if upload is None:
            raise ApiError(404, "not_found", "The upload session does not exist.")
        await authorize_project_action(session, user, upload.project_id, action)
        return upload

    return dependency
