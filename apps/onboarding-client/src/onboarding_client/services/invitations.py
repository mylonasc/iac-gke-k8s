import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from onboarding_client.config import get_settings
from onboarding_client.integrations.resend_client import EmailSender
from onboarding_client.models import (
    DeliveryAttempt,
    DeliveryChannel,
    DeliveryStatus,
    Invitation,
    InvitationRole,
    InvitationStatus,
    Profile,
    ProfileStatus,
    VerificationToken,
)
from onboarding_client.schemas import InvitationCreate
from onboarding_client.services.audit import log_audit
from onboarding_client.services.roles import get_roles_by_slugs


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def hash_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def build_confirmation_url(raw_token: str) -> str:
    settings = get_settings()
    base = settings.public_base_url.rstrip("/")
    return f"{base}/confirm/{raw_token}"


def create_invitation(
    db: Session,
    *,
    payload: InvitationCreate,
    email_sender: EmailSender,
) -> tuple[Invitation, str]:
    email = payload.email.strip().lower()
    profile = db.query(Profile).filter(Profile.email == email).first()
    if not profile:
        profile = Profile(email=email, status=ProfileStatus.invited)
        db.add(profile)
        db.flush()

    roles = get_roles_by_slugs(db, payload.role_slugs)
    now = _utcnow()
    invitation = Invitation(
        email=email,
        target_channel=DeliveryChannel.email,
        target_value=email,
        profile_id=profile.id,
        requested_by=payload.requested_by,
        status=InvitationStatus.pending,
        expires_at=now + timedelta(seconds=payload.ttl_seconds),
    )
    db.add(invitation)
    db.flush()

    for role in roles:
        db.add(InvitationRole(invitation_id=invitation.id, role_id=role.id))

    raw_token = secrets.token_urlsafe(24)
    db.add(
        VerificationToken(
            invitation_id=invitation.id,
            token_hash=hash_token(raw_token),
            channel=DeliveryChannel.email,
            expires_at=invitation.expires_at,
        )
    )
    db.flush()

    confirmation_url = build_confirmation_url(raw_token)
    try:
        sent = email_sender.send_invitation(
            recipient=email,
            confirmation_url=confirmation_url,
            invitation_id=invitation.id,
        )
        invitation.status = InvitationStatus.sent
        db.add(
            DeliveryAttempt(
                invitation_id=invitation.id,
                channel=DeliveryChannel.email,
                provider="resend",
                provider_message_id=sent.message_id,
                status=DeliveryStatus.sent,
            )
        )
    except Exception as exc:
        db.add(
            DeliveryAttempt(
                invitation_id=invitation.id,
                channel=DeliveryChannel.email,
                provider="resend",
                status=DeliveryStatus.failed,
                error_message=str(exc),
            )
        )
        log_audit(
            db,
            actor=payload.requested_by or "system",
            action="send_invitation_failed",
            target_type="invitation",
            target_id=str(invitation.id),
            details={"error": str(exc)},
        )
        raise

    log_audit(
        db,
        actor=payload.requested_by or "system",
        action="create_invitation",
        target_type="invitation",
        target_id=str(invitation.id),
        details={"email": email, "roles": [role.slug for role in roles]},
    )
    db.flush()
    return invitation, raw_token


def get_invitation_by_token(
    db: Session, raw_token: str
) -> tuple[Invitation, VerificationToken]:
    token_hash = hash_token(raw_token)
    token = (
        db.query(VerificationToken)
        .filter(VerificationToken.token_hash == token_hash)
        .first()
    )
    if not token:
        raise ValueError("Invalid token")
    invitation = token.invitation
    now = _utcnow()
    if token.consumed_at is not None:
        raise ValueError("Token already consumed")
    if token.expires_at < now or invitation.expires_at < now:
        invitation.status = InvitationStatus.expired
        db.flush()
        raise ValueError("Token expired")
    if invitation.status in {InvitationStatus.cancelled, InvitationStatus.expired}:
        raise ValueError("Invitation is not active")
    return invitation, token


def confirm_invitation(db: Session, raw_token: str) -> Invitation:
    invitation, _ = get_invitation_by_token(db, raw_token)
    profile = invitation.profile
    if invitation.status in {InvitationStatus.pending, InvitationStatus.sent}:
        invitation.status = InvitationStatus.confirmed
        if profile is not None and profile.status == ProfileStatus.invited:
            profile.status = ProfileStatus.confirmed
    db.flush()
    return invitation


def list_invitations(db: Session) -> list[Invitation]:
    return db.query(Invitation).order_by(Invitation.id.desc()).all()
