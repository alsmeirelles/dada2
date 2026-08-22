"""Authentication endpoints covering login, refresh rotation, and logout."""

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from dada_api.api.deps import get_current_user
from dada_api.core.config import get_settings
from dada_api.core.errors import ApiError
from dada_api.core.security import create_access_token
from dada_api.db.session import get_session
from dada_api.models.user import User
from dada_api.schemas.auth import LoginRequest, TokenResponse
from dada_api.schemas.user import UserRead
from dada_api.services.auth_sessions import (
    issue_refresh_session,
    revoke_presented_session,
    rotate_refresh_session,
)
from dada_api.services.users import access_token_roles, authenticate_user

router = APIRouter()

REFRESH_COOKIE_NAME = "dada_refresh"
REFRESH_COOKIE_PATH = "/api/v1/auth"


def _set_refresh_cookie(response: Response, token: str) -> None:
    """Attach a refresh credential as a first-party, script-inaccessible cookie.

    Args:
        response: Response carrying the credential back to the client.
        token: Plaintext refresh token.
    """
    settings = get_settings()
    response.set_cookie(
        key=REFRESH_COOKIE_NAME,
        value=token,
        max_age=settings.refresh_token_expire_days * 24 * 60 * 60,
        path=REFRESH_COOKIE_PATH,
        secure=settings.refresh_cookie_secure,
        httponly=True,
        samesite=settings.refresh_cookie_samesite,
    )


@router.post("/token", response_model=TokenResponse)
async def login_for_access_token(
    credentials: LoginRequest,
    response: Response,
    session: AsyncSession = Depends(get_session),
) -> TokenResponse:
    """Authenticate a user, returning a bearer token and a refresh cookie.

    Args:
        credentials: Supplied username and password.
        response: Response carrying the refresh cookie.
        session: Active database session.

    Returns:
        The bearer access token.

    Raises:
        HTTPException: 401 when the credentials are invalid.
    """
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

    _set_refresh_cookie(response, await issue_refresh_session(session, user))
    return TokenResponse(
        access_token=create_access_token(user.username, access_token_roles(user))
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh_access_token(
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_session),
) -> TokenResponse:
    """Rotate the refresh credential and issue a fresh access token.

    Args:
        request: Request carrying the refresh cookie.
        response: Response carrying the rotated cookie.
        session: Active database session.

    Returns:
        A new bearer access token.

    Raises:
        ApiError: 401 when no refresh credential is present.
    """
    presented = request.cookies.get(REFRESH_COOKIE_NAME)
    if not presented:
        raise ApiError(
            401,
            "missing_refresh_token",
            "No refresh credential was supplied.",
        )

    user, token = await rotate_refresh_session(session, presented)
    _set_refresh_cookie(response, token)
    return TokenResponse(
        access_token=create_access_token(user.username, access_token_roles(user))
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_session),
) -> None:
    """Revoke the presented refresh session and clear its cookie.

    Args:
        request: Request carrying the refresh cookie.
        response: Response clearing the cookie.
        session: Active database session.
    """
    presented = request.cookies.get(REFRESH_COOKIE_NAME)
    if presented:
        await revoke_presented_session(session, presented)
    response.delete_cookie(REFRESH_COOKIE_NAME, path=REFRESH_COOKIE_PATH)


@router.get("/me", response_model=UserRead)
async def read_current_user(user: User = Depends(get_current_user)) -> User:
    """Return the currently authenticated user.

    Args:
        user: Authenticated user.

    Returns:
        The authenticated user.
    """
    return user
