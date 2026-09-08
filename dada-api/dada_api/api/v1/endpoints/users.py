"""Global user administration routes, restricted to administrators."""

from fastapi import APIRouter, Depends, Header, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from dada_api.api.deps import require_administrator
from dada_api.core.errors import ApiError
from dada_api.db.session import get_session
from dada_api.models.user import User
from dada_api.schemas.user import (
    AdministratorPasswordReset,
    UserCreate,
    UserPage,
    UserRead,
    UserUpdate,
)
from dada_api.services import users as user_service

router = APIRouter()


def parse_if_match(value: str | None) -> int:
    """Return the expected version carried by an ``If-Match`` header.

    The header carries the bare version. Surrounding quotes are tolerated so a
    client sending a conventional entity tag still works.

    Args:
        value: Raw header value, absent when the client sent none.

    Returns:
        The expected version.

    Raises:
        ApiError: 400 when the header is missing or is not a version.
    """
    candidate = (value or "").strip().strip('"')
    if not candidate.isdigit():
        raise ApiError(
            400,
            "invalid_if_match",
            "If-Match must carry the expected user version.",
        )
    return int(candidate)


@router.get("/users", response_model=UserPage)
async def list_users(
    cursor: str | None = Query(default=None),
    active: bool | None = Query(default=None),
    _: User = Depends(require_administrator),
    session: AsyncSession = Depends(get_session),
) -> UserPage:
    """List users. Administrators only.

    Args:
        cursor: Opaque cursor from a previous page.
        active: Restrict to active or inactive users when supplied.
        _: Authenticated administrator.
        session: Active database session.

    Returns:
        One page of users with the cursor for the next one.
    """
    items, next_cursor = await user_service.list_users(session, cursor, active)
    return UserPage(
        items=[UserRead.model_validate(item) for item in items],
        next_cursor=next_cursor,
    )


@router.post("/users", response_model=UserRead, status_code=status.HTTP_201_CREATED)
async def create_user(
    request: UserCreate,
    actor: User = Depends(require_administrator),
    session: AsyncSession = Depends(get_session),
) -> User:
    """Create a user. Administrators only.

    Args:
        request: Validated creation request.
        actor: Authenticated administrator.
        session: Active database session.

    Returns:
        The created user.
    """
    return await user_service.create_user(session, actor, request)


@router.get("/users/{user_id}", response_model=UserRead)
async def read_user(
    user_id: str,
    _: User = Depends(require_administrator),
    session: AsyncSession = Depends(get_session),
) -> User:
    """Return one user. Administrators only.

    Args:
        user_id: User being read.
        _: Authenticated administrator.
        session: Active database session.

    Returns:
        The requested user.
    """
    return await user_service.get_user(session, user_id)


@router.patch("/users/{user_id}", response_model=UserRead)
async def update_user(
    user_id: str,
    request: UserUpdate,
    actor: User = Depends(require_administrator),
    session: AsyncSession = Depends(get_session),
) -> User:
    """Apply a versioned update to a user. Administrators only.

    Args:
        user_id: User being changed.
        request: Validated update carrying the expected version.
        actor: Authenticated administrator.
        session: Active database session.

    Returns:
        The updated user.
    """
    user = await user_service.get_user(session, user_id)
    return await user_service.update_user(session, actor, user, request)


@router.post("/users/{user_id}/reset-password", status_code=status.HTTP_204_NO_CONTENT)
async def reset_user_password(
    user_id: str,
    request: AdministratorPasswordReset,
    actor: User = Depends(require_administrator),
    session: AsyncSession = Depends(get_session),
) -> None:
    """Replace a user's password and revoke their sessions. Administrators only.

    Args:
        user_id: User whose password is replaced.
        request: Validated replacement password.
        actor: Authenticated administrator.
        session: Active database session.
    """
    user = await user_service.get_user(session, user_id)
    await user_service.reset_password(session, actor, user, request.new_password)


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: str,
    if_match: str | None = Header(default=None, alias="If-Match"),
    actor: User = Depends(require_administrator),
    session: AsyncSession = Depends(get_session),
) -> None:
    """Permanently delete a user. Administrators only.

    The deletion is terminal: no restore window exists in this release.

    Args:
        user_id: User being removed.
        if_match: Expected user version.
        actor: Authenticated administrator.
        session: Active database session.

    Raises:
        ApiError: 409 when the supplied version is not the current one.
    """
    expected_version = parse_if_match(if_match)
    user = await user_service.get_user(session, user_id)
    if expected_version != user.version:
        raise ApiError(
            409,
            "version_conflict",
            "The user changed since it was read.",
            details={"expected_version": user.version},
        )
    await user_service.delete_user(session, actor, user)
