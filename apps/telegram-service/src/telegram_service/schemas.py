from datetime import datetime

from pydantic import BaseModel, Field

from telegram_service.models import ConnectionType, ContextMode


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=120)
    password: str = Field(min_length=8, max_length=128)
    is_admin: bool = False


class UserOut(BaseModel):
    id: int
    username: str
    is_admin: bool
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class ConnectionCreate(BaseModel):
    name: str = Field(min_length=3, max_length=200)
    type: ConnectionType
    owner_user_id: int | None = None
    bot_username: str | None = None
    phone_number: str | None = None
    secret_ref_token: str | None = None
    secret_ref_session: str | None = None
    webhook_path: str | None = None


class ConnectionOut(BaseModel):
    id: int
    name: str
    type: ConnectionType
    owner_user_id: int | None
    bot_username: str | None
    phone_number: str | None
    secret_ref_token: str | None
    secret_ref_session: str | None
    webhook_path: str | None
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class ContextCreate(BaseModel):
    connection_id: int
    name: str = Field(min_length=2, max_length=120)
    mode: ContextMode
    chat_id: str = Field(min_length=1, max_length=80)


class ContextOut(BaseModel):
    id: int
    connection_id: int
    name: str
    mode: ContextMode
    chat_id: str
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class SendMessageRequest(BaseModel):
    text: str = Field(min_length=1, max_length=4096)


class RuntimePrincipal(BaseModel):
    subject: str
    username: str | None = None
    email: str | None = None


class RuntimeIdentity(BaseModel):
    user_id: int
    subject: str
    username: str | None = None
    email: str | None = None


class UserLoginStartRequest(BaseModel):
    connection_id: int


class UserLoginVerifyRequest(BaseModel):
    connection_id: int
    code: str
    password: str | None = None


class OtpIssueRequest(BaseModel):
    context_id: int
    target_label: str | None = None
    purpose: str = Field(default="auth", max_length=120)
    ttl_seconds: int = Field(default=300, ge=60, le=1800)
    length: int = Field(default=6, ge=4, le=10)


class OtpIssueResponse(BaseModel):
    ok: bool
    challenge_id: str
    expires_at: datetime
    context_id: int


class OtpVerifyRequest(BaseModel):
    challenge_id: str
    code: str = Field(min_length=4, max_length=10)


class OtpVerifyResponse(BaseModel):
    ok: bool
    valid: bool
    reason: str | None = None


class ManagedSecretCreate(BaseModel):
    name: str = Field(min_length=2, max_length=190)
    value: str = Field(min_length=1, max_length=8192)
    secret_type: str = Field(default="generic", max_length=40)
    description: str | None = Field(default=None, max_length=255)


class ManagedSecretRotate(BaseModel):
    value: str = Field(min_length=1, max_length=8192)


class ManagedSecretOut(BaseModel):
    id: int
    name: str
    secret_type: str
    description: str | None
    version: int
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class OnboardingCreateRequest(BaseModel):
    connection_id: int
    target_label: str | None = None
    ttl_seconds: int = Field(default=900, ge=60, le=86400)


class OnboardingProcessRequest(BaseModel):
    connection_id: int
    offset: int | None = None
    limit: int = Field(default=50, ge=1, le=100)


class OnboardingOut(BaseModel):
    id: int
    token: str
    connection_id: int
    target_label: str | None
    status: str
    chat_id: str | None
    telegram_user_id: str | None
    telegram_username: str | None
    context_id: int | None
    expires_at: datetime
    completed_at: datetime | None
    created_at: datetime
    deep_link: str | None = None
    qr_data_url: str | None = None

    model_config = {"from_attributes": True}


class SelfServiceConnectionCreate(BaseModel):
    name: str = Field(min_length=3, max_length=200)
    type: ConnectionType
    bot_username: str | None = Field(default=None, max_length=200)
    phone_number: str | None = Field(default=None, max_length=50)
    bot_token: str | None = Field(default=None, min_length=1, max_length=8192)
    session_string: str | None = Field(default=None, min_length=1, max_length=8192)


class SelfServiceContextCreate(BaseModel):
    connection_id: int
    name: str = Field(min_length=2, max_length=120)
    mode: ContextMode
    chat_id: str = Field(min_length=1, max_length=80)
