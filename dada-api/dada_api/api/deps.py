"""FastAPI dependencies for authentication and authorization."""

from collections.abc import Callable

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from dada_api.core.security import decode_access_token
from dada_api.db.session import get_session
from dada_api.models.user import User, UserRole
from dada_api.services.users import get_user_by_username

bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    session: AsyncSession = Depends(get_session),
) -> User:
    """Resolve the authenticated user from the bearer token."""
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


def require_roles(*allowed_roles: UserRole) -> Callable[[User], User]:
    """Build a dependency that requires any one of the provided roles."""
    allowed_role_set = set(allowed_roles)

    async def dependency(user: User = Depends(get_current_user)) -> User:
        """Return the current user when role authorization passes."""
        if user.role not in allowed_role_set:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="The authenticated user is not allowed to perform this action.",
            )
        return user

    return dependency


RequireAnnotator = require_roles(UserRole.annotator, UserRole.admin)
RequireAdmin = require_roles(UserRole.admin)
