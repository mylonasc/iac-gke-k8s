from datetime import datetime
from enum import Enum

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum as SqlEnum,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from telegram_service.database import Base


class ConnectionType(str, Enum):
    bot = "bot"
    user = "user"


class ContextMode(str, Enum):
    send_only = "send_only"
    send_receive = "send_receive"
    receive_only = "receive_only"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    connections: Mapped[list["TelegramConnection"]] = relationship(
        back_populates="owner"
    )


class TelegramConnection(Base):
    __tablename__ = "telegram_connections"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True)
    type: Mapped[ConnectionType] = mapped_column(SqlEnum(ConnectionType), index=True)
    owner_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    bot_username: Mapped[str | None] = mapped_column(String(200), nullable=True)
    phone_number: Mapped[str | None] = mapped_column(String(50), nullable=True)
    secret_ref_token: Mapped[str | None] = mapped_column(String(512), nullable=True)
    secret_ref_session: Mapped[str | None] = mapped_column(String(512), nullable=True)
    webhook_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    owner: Mapped[User | None] = relationship(back_populates="connections")
    contexts: Mapped[list["MessagingContext"]] = relationship(
        back_populates="connection", cascade="all,delete-orphan"
    )


class MessagingContext(Base):
    __tablename__ = "messaging_contexts"
    __table_args__ = (
        UniqueConstraint("connection_id", "name", name="uq_connection_context_name"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    connection_id: Mapped[int] = mapped_column(
        ForeignKey("telegram_connections.id"), index=True
    )
    name: Mapped[str] = mapped_column(String(120))
    mode: Mapped[ContextMode] = mapped_column(SqlEnum(ContextMode), index=True)
    chat_id: Mapped[str] = mapped_column(String(80))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    connection: Mapped[TelegramConnection] = relationship(back_populates="contexts")


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    actor: Mapped[str] = mapped_column(String(255), index=True)
    action: Mapped[str] = mapped_column(String(255), index=True)
    target_type: Mapped[str] = mapped_column(String(80), index=True)
    target_id: Mapped[str] = mapped_column(String(120), index=True)
    details: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, index=True
    )


class OtpChallenge(Base):
    __tablename__ = "otp_challenges"

    id: Mapped[int] = mapped_column(primary_key=True)
    challenge_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    context_id: Mapped[int] = mapped_column(
        ForeignKey("messaging_contexts.id"), index=True
    )
    principal_subject: Mapped[str] = mapped_column(String(255), index=True)
    target_label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    purpose: Mapped[str] = mapped_column(String(120), default="auth")
    otp_hash: Mapped[str] = mapped_column(String(128))
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    attempts: Mapped[int] = mapped_column(default=0)
    max_attempts: Mapped[int] = mapped_column(default=5)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, index=True
    )

    context: Mapped[MessagingContext] = relationship()


class ManagedSecret(Base):
    __tablename__ = "managed_secrets"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(190), unique=True, index=True)
    secret_type: Mapped[str] = mapped_column(String(40), default="generic")
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    encrypted_value: Mapped[str] = mapped_column(Text)
    version: Mapped[int] = mapped_column(default=1)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )


class OnboardingLink(Base):
    __tablename__ = "onboarding_links"

    id: Mapped[int] = mapped_column(primary_key=True)
    token: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    connection_id: Mapped[int] = mapped_column(
        ForeignKey("telegram_connections.id"), index=True
    )
    target_label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="pending", index=True)
    chat_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    telegram_user_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    telegram_username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    context_id: Mapped[int | None] = mapped_column(
        ForeignKey("messaging_contexts.id"), nullable=True, index=True
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, index=True
    )

    connection: Mapped[TelegramConnection] = relationship()
    context: Mapped[MessagingContext | None] = relationship()
