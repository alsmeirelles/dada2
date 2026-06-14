"""User management endpoints."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from dada_api.api.deps import RequireAdmin
from dada_api.db.session import get_session
from dada_api.models.user import User
from dada_api.schemas.user import UserCreate, UserRead
from dada_api.services.users import create_user

router = APIRouter()


@router.get("/", response_model=list[UserRead])
async def list_users(
    _: User = Depends(RequireAdmin),
    session: AsyncSession = Depends(get_session),
) -> list[User]:
    """List users. Admin-only."""
    result = await session.scalars(select(User).order_by(User.username))
    return list(result)


@router.post("/", response_model=UserRead, status_code=status.HTTP_201_CREATED)
async def create_api_user(
    user_create: UserCreate,
    _: User = Depends(RequireAdmin),
    session: AsyncSession = Depends(get_session),
) -> User:
    """Create a user. Admin-only."""
    try:
        return await create_user(session, user_create)
    except IntegrityError as error:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A user with this username already exists.",
        ) from error
