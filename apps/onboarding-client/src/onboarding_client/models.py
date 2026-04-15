from datetime import datetime
from enum import Enum

from sqlalchemy import (
    DateTime,
    Enum as SqlEnum,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from onboarding_client.database import Base


class InvitationStatus(str, Enum):
    pending = "pending"
    sent = "sent"
    confirmed = "confirmed"
    submitted = "submitted"
    expired = "expired"
    cancelled = "cancelled"


class ProfileStatus(str, Enum):
    invited = "invited"
    confirmed = "confirmed"
    submitted = "submitted"
    approved = "approved"
    rejected = "rejected"
    provisioned = "provisioned"


class DeliveryChannel(str, Enum):
    email = "email"
    telegram = "telegram"


class DeliveryStatus(str, Enum):
    sent = "sent"
    failed = "failed"


class Profile(Base):
    __tablename__ = "profiles"

    id: Mapped[int] = mapped_column(primary_key=True)
    dex_subject: Mapped[str | None] = mapped_column(
        String(255), unique=True, nullable=True, index=True
    )
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    username: Mapped[str | None] = mapped_column(String(120), nullable=True)
    full_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    organization: Mapped[str | None] = mapped_column(String(255), nullable=True)
    team: Mapped[str | None] = mapped_column(String(255), nullable=True)
    justification: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[ProfileStatus] = mapped_column(
        SqlEnum(ProfileStatus), default=ProfileStatus.invited, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    invitations: Mapped[list["Invitation"]] = relationship(back_populates="profile")
    role_assignments: Mapped[list["ProfileRole"]] = relationship(
        back_populates="profile", cascade="all,delete-orphan"
    )


class Role(Base):
    __tablename__ = "roles"

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, index=True
    )

    profile_assignments: Mapped[list["ProfileRole"]] = relationship(
        back_populates="role", cascade="all,delete-orphan"
    )


class ProfileRole(Base):
    __tablename__ = "profile_roles"
    __table_args__ = (
        UniqueConstraint("profile_id", "role_id", name="uq_profile_role"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    profile_id: Mapped[int] = mapped_column(ForeignKey("profiles.id"), index=True)
    role_id: Mapped[int] = mapped_column(ForeignKey("roles.id"), index=True)
    source: Mapped[str] = mapped_column(String(40), default="approved")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    profile: Mapped[Profile] = relationship(back_populates="role_assignments")
    role: Mapped[Role] = relationship(back_populates="profile_assignments")


class Invitation(Base):
    __tablename__ = "invitations"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), index=True)
    target_channel: Mapped[DeliveryChannel] = mapped_column(
        SqlEnum(DeliveryChannel), default=DeliveryChannel.email
    )
    target_value: Mapped[str] = mapped_column(String(255))
    profile_id: Mapped[int | None] = mapped_column(
        ForeignKey("profiles.id"), nullable=True, index=True
    )
    requested_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[InvitationStatus] = mapped_column(
        SqlEnum(InvitationStatus), default=InvitationStatus.pending, index=True
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    profile: Mapped[Profile | None] = relationship(back_populates="invitations")
    tokens: Mapped[list["VerificationToken"]] = relationship(
        back_populates="invitation", cascade="all,delete-orphan"
    )
    requested_roles: Mapped[list["InvitationRole"]] = relationship(
        back_populates="invitation", cascade="all,delete-orphan"
    )
    deliveries: Mapped[list["DeliveryAttempt"]] = relationship(
        back_populates="invitation", cascade="all,delete-orphan"
    )


class InvitationRole(Base):
    __tablename__ = "invitation_roles"
    __table_args__ = (
        UniqueConstraint("invitation_id", "role_id", name="uq_invitation_role"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    invitation_id: Mapped[int] = mapped_column(ForeignKey("invitations.id"), index=True)
    role_id: Mapped[int] = mapped_column(ForeignKey("roles.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    invitation: Mapped[Invitation] = relationship(back_populates="requested_roles")
    role: Mapped[Role] = relationship()


class VerificationToken(Base):
    __tablename__ = "verification_tokens"

    id: Mapped[int] = mapped_column(primary_key=True)
    invitation_id: Mapped[int] = mapped_column(ForeignKey("invitations.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    channel: Mapped[DeliveryChannel] = mapped_column(
        SqlEnum(DeliveryChannel), default=DeliveryChannel.email
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, index=True
    )

    invitation: Mapped[Invitation] = relationship(back_populates="tokens")


class DeliveryAttempt(Base):
    __tablename__ = "delivery_attempts"

    id: Mapped[int] = mapped_column(primary_key=True)
    invitation_id: Mapped[int] = mapped_column(ForeignKey("invitations.id"), index=True)
    channel: Mapped[DeliveryChannel] = mapped_column(
        SqlEnum(DeliveryChannel), default=DeliveryChannel.email
    )
    provider: Mapped[str] = mapped_column(String(40), default="resend")
    provider_message_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[DeliveryStatus] = mapped_column(
        SqlEnum(DeliveryStatus), default=DeliveryStatus.sent
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, index=True
    )

    invitation: Mapped[Invitation] = relationship(back_populates="deliveries")


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
