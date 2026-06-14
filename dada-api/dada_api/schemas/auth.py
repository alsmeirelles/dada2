"""Authentication request and response schemas."""

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    """JSON login payload."""

    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=8, max_length=128)


class TokenResponse(BaseModel):
    """Bearer token response."""

    access_token: str
    token_type: str = "bearer"
