"""User management endpoints."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from dada_api.api.deps import require_administrator
from dada_api.db.session import get_session
from dada_api.models.user import User
from dada_api.schemas.user import UserCreate, UserRead
from dada_api.services.users import create_user

router = APIRouter()


@router.get("/", response_model=list[UserRead])
async def list_users(
    _: User = Depends(require_administrator),
    session: AsyncSession = Depends(get_session),
) -> list[User]:
    """List users. Administrators only.

    Args:
        _: Authenticated administrator.
        session: Active database session.

    Returns:
        Every user ordered by username.
    """
    result = await session.scalars(select(User).order_by(User.username))
    return list(result)


@router.post("/", response_model=UserRead, status_code=status.HTTP_201_CREATED)
async def create_api_user(
    user_create: UserCreate,
    _: User = Depends(require_administrator),
    session: AsyncSession = Depends(get_session),
) -> User:
    """Create a user. Administrators only.

    Args:
        user_create: Validated creation request.
        _: Authenticated administrator.
        session: Active database session.

    Returns:
        The created user.

    Raises:
        HTTPException: 409 when the username is already taken.
    """
    try:
        return await create_user(session, user_create)
    except IntegrityError as error:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A user with this username already exists.",
        ) from error
