"""User request and response schemas."""

from datetime import datetime

from pydantic import BaseModel, Field


class UserCreate(BaseModel):
    """Administrator request to create a user."""

    username: str = Field(min_length=3, max_length=64)
    display_name: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=8, max_length=128)
    is_administrator: bool = False
    is_active: bool = True


class UserRead(BaseModel):
    """Public user representation."""

    id: str
    username: str
    display_name: str
    is_administrator: bool
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}
