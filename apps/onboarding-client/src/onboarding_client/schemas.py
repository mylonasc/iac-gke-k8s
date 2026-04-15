from datetime import datetime

from pydantic import BaseModel, EmailStr, Field

from onboarding_client.models import InvitationStatus, ProfileStatus


class RoleCreate(BaseModel):
    slug: str = Field(min_length=2, max_length=120)
    display_name: str = Field(min_length=2, max_length=255)
    description: str | None = Field(default=None, max_length=2000)


class RoleOut(BaseModel):
    id: int
    slug: str
    display_name: str
    description: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class InvitationCreate(BaseModel):
    email: EmailStr
    requested_by: str | None = Field(default=None, max_length=255)
    role_slugs: list[str] = Field(default_factory=list)
    ttl_seconds: int = Field(default=86400, ge=300, le=604800)


class InvitationOut(BaseModel):
    id: int
    email: EmailStr
    status: InvitationStatus
    requested_by: str | None
    expires_at: datetime
    created_at: datetime
    role_slugs: list[str]
    confirmation_url: str | None = None


class ProfileOut(BaseModel):
    id: int
    dex_subject: str | None
    email: EmailStr
    username: str | None
    full_name: str | None
    organization: str | None
    team: str | None
    justification: str | None
    status: ProfileStatus
    created_at: datetime
    updated_at: datetime
    role_slugs: list[str]


class ProfileApproveRequest(BaseModel):
    role_slugs: list[str] = Field(default_factory=list)


class RuntimePrincipal(BaseModel):
    subject: str
    username: str | None = None
    email: EmailStr | None = None


class RuntimeIdentity(BaseModel):
    subject: str
    email: EmailStr | None = None
    username: str | None = None
    profile_status: ProfileStatus | None = None


class RuntimeRolesOut(BaseModel):
    subject: str
    email: EmailStr | None = None
    roles: list[str]
