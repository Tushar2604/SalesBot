"""Auth and tenancy request/response schemas."""

from __future__ import annotations

import re
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.models.tenancy import WorkspaceRole

_PASSWORD_MIN = 10


def _validate_password(value: str) -> str:
    if len(value) < _PASSWORD_MIN:
        raise ValueError(f"password must be at least {_PASSWORD_MIN} characters")
    if not re.search(r"[A-Za-z]", value) or not re.search(r"\d", value):
        raise ValueError("password must contain both letters and digits")
    return value


class SignupRequest(BaseModel):
    email: EmailStr
    password: str
    full_name: str = Field(default="", max_length=160)
    workspace_name: str = Field(default="", max_length=160)

    _check_password = field_validator("password")(_validate_password)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"  # noqa: S105 - scheme name, not a secret
    expires_in: int
    # Refresh token travels in an httpOnly cookie, never in the body.


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: EmailStr
    full_name: str
    timezone: str
    is_active: bool
    created_at: datetime


class WorkspaceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    slug: str
    outreach_paused: bool
    created_at: datetime


class MembershipResponse(BaseModel):
    workspace: WorkspaceResponse
    role: WorkspaceRole


class MeResponse(BaseModel):
    user: UserResponse
    workspaces: list[MembershipResponse]


class WorkspaceCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=160)


class WorkspaceUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    outreach_paused: bool | None = None


class MemberResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user: UserResponse
    role: WorkspaceRole
    created_at: datetime


class MemberRoleUpdateRequest(BaseModel):
    role: WorkspaceRole


class InviteCreateRequest(BaseModel):
    email: EmailStr
    role: WorkspaceRole = WorkspaceRole.MEMBER


class InviteResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: EmailStr
    role: WorkspaceRole
    status: str
    expires_at: datetime
    created_at: datetime


class InviteCreatedResponse(InviteResponse):
    # Returned exactly once, at creation time. Never retrievable afterwards.
    invite_url: str


class InviteAcceptRequest(BaseModel):
    token: str
    # Supplied only when the invited email has no account yet.
    password: str | None = None
    full_name: str = Field(default="", max_length=160)

    @field_validator("password")
    @classmethod
    def _check_optional_password(cls, value: str | None) -> str | None:
        return _validate_password(value) if value is not None else None
