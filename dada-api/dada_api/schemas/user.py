"""User request and response schemas used by the v1 OpenAPI surface."""

from datetime import datetime

from pydantic import BaseModel, Field

PASSWORD_FIELD = Field(min_length=8, max_length=128)


class UserCreate(BaseModel):
    """Administrator request to create a user."""

    username: str = Field(min_length=3, max_length=64)
    display_name: str = Field(min_length=1, max_length=120)
    password: str = PASSWORD_FIELD
    is_administrator: bool = False
    is_active: bool = True


class UserUpdate(BaseModel):
    """Optimistically versioned editable user fields.

    ``username`` is absent on purpose: it is immutable after creation, so
    immutability is a property of the contract rather than a runtime check.
    """

    display_name: str | None = Field(default=None, min_length=1, max_length=120)
    is_administrator: bool | None = None
    is_active: bool | None = None
    version: int = Field(ge=1)


class AdministratorPasswordReset(BaseModel):
    """Administrator request to replace another user's password."""

    new_password: str = PASSWORD_FIELD


class PasswordChange(BaseModel):
    """Authenticated user's request to replace their own password."""

    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = PASSWORD_FIELD


class UserRead(BaseModel):
    """Public user representation."""

    id: str
    username: str
    display_name: str
    is_administrator: bool
    is_active: bool
    version: int
    created_at: datetime

    model_config = {"from_attributes": True}


class UserPage(BaseModel):
    """Cursor-paginated user collection."""

    items: list[UserRead]
    next_cursor: str | None = None
