from datetime import UTC, datetime

from sqlalchemy.orm import Session

from onboarding_client.models import (
    InvitationStatus,
    Profile,
    ProfileRole,
    ProfileStatus,
)
from onboarding_client.schemas import ProfileApproveRequest, RuntimePrincipal
from onboarding_client.services.audit import log_audit
from onboarding_client.services.invitations import get_invitation_by_token
from onboarding_client.services.roles import get_roles_by_slugs


def submit_profile(
    db: Session,
    *,
    raw_token: str,
    username: str | None,
    full_name: str,
    organization: str | None,
    team: str | None,
    justification: str | None,
) -> Profile:
    invitation, token = get_invitation_by_token(db, raw_token)
    profile = invitation.profile
    if profile is None:
        raise ValueError("Invitation profile missing")
    profile.username = username.strip() if username else None
    profile.full_name = full_name.strip()
    profile.organization = organization.strip() if organization else None
    profile.team = team.strip() if team else None
    profile.justification = justification.strip() if justification else None
    profile.status = ProfileStatus.submitted
    invitation.status = InvitationStatus.submitted
    token.consumed_at = datetime.now(UTC).replace(tzinfo=None)
    log_audit(
        db,
        actor=profile.email,
        action="submit_profile",
        target_type="profile",
        target_id=str(profile.id),
        details={"invitation_id": invitation.id},
    )
    db.flush()
    return profile


def list_profiles(db: Session) -> list[Profile]:
    return db.query(Profile).order_by(Profile.id.asc()).all()


def get_profile_by_id(db: Session, profile_id: int) -> Profile | None:
    return db.query(Profile).filter(Profile.id == profile_id).first()


def approve_profile(
    db: Session,
    *,
    profile: Profile,
    payload: ProfileApproveRequest,
    actor: str,
) -> Profile:
    roles = get_roles_by_slugs(db, payload.role_slugs)
    profile.role_assignments.clear()
    db.flush()
    for role in roles:
        db.add(ProfileRole(profile_id=profile.id, role_id=role.id, source="approved"))
    profile.status = ProfileStatus.approved
    log_audit(
        db,
        actor=actor,
        action="approve_profile",
        target_type="profile",
        target_id=str(profile.id),
        details={"roles": [role.slug for role in roles]},
    )
    db.flush()
    return profile


def reject_profile(db: Session, *, profile: Profile, actor: str) -> Profile:
    profile.status = ProfileStatus.rejected
    log_audit(
        db,
        actor=actor,
        action="reject_profile",
        target_type="profile",
        target_id=str(profile.id),
        details=None,
    )
    db.flush()
    return profile


def resolve_profile_for_principal(
    db: Session, principal: RuntimePrincipal
) -> Profile | None:
    profile = db.query(Profile).filter(Profile.dex_subject == principal.subject).first()
    if profile:
        return profile
    email = (principal.email or "").strip().lower()
    if not email:
        return None
    profile = db.query(Profile).filter(Profile.email == email).first()
    if not profile:
        return None
    if profile.dex_subject is None:
        profile.dex_subject = principal.subject
        db.flush()
    return profile


def get_active_role_slugs(profile: Profile | None) -> list[str]:
    if not profile or profile.status not in {
        ProfileStatus.approved,
        ProfileStatus.provisioned,
    }:
        return []
    return sorted(assignment.role.slug for assignment in profile.role_assignments)
