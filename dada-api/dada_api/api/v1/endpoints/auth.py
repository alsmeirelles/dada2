"""Authentication endpoints."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from dada_api.api.deps import get_current_user
from dada_api.core.security import create_access_token
from dada_api.db.session import get_session
from dada_api.models.user import User
from dada_api.schemas.auth import LoginRequest, TokenResponse
from dada_api.schemas.user import UserRead
from dada_api.services.users import authenticate_user

router = APIRouter()


@router.post("/token", response_model=TokenResponse)
async def login_for_access_token(
    credentials: LoginRequest,
    session: AsyncSession = Depends(get_session),
) -> TokenResponse:
    """Authenticate a user and return a bearer token."""
    user = await authenticate_user(
        session,
        credentials.username,
        credentials.password,
    )
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return TokenResponse(
        access_token=create_access_token(user.username, [user.role.value])
    )


@router.get("/me", response_model=UserRead)
async def read_current_user(user: User = Depends(get_current_user)) -> User:
    """Return the currently authenticated user."""
    return user
