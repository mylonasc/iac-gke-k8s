from fastapi import APIRouter, HTTPException, status

from onboarding_client.deps import DbSession, EmailSenderDep
from onboarding_client.schemas import (
    InvitationCreate,
    InvitationOut,
    ProfileApproveRequest,
    ProfileOut,
    RoleCreate,
    RoleOut,
)
from onboarding_client.services.invitations import create_invitation, list_invitations
from onboarding_client.services.profiles import (
    approve_profile,
    get_profile_by_id,
    list_profiles,
    reject_profile,
)
from onboarding_client.services.roles import create_role, list_roles

router = APIRouter(prefix="/api/admin", tags=["admin-api"])


def _serialize_invitation(item, confirmation_url: str | None = None) -> InvitationOut:
    return InvitationOut(
        id=item.id,
        email=item.email,
        status=item.status,
        requested_by=item.requested_by,
        expires_at=item.expires_at,
        created_at=item.created_at,
        role_slugs=sorted(link.role.slug for link in item.requested_roles),
        confirmation_url=confirmation_url,
    )


def _serialize_profile(item) -> ProfileOut:
    return ProfileOut(
        id=item.id,
        dex_subject=item.dex_subject,
        email=item.email,
        username=item.username,
        full_name=item.full_name,
        organization=item.organization,
        team=item.team,
        justification=item.justification,
        status=item.status,
        created_at=item.created_at,
        updated_at=item.updated_at,
        role_slugs=sorted(assignment.role.slug for assignment in item.role_assignments),
    )


@router.post("/roles", response_model=RoleOut, status_code=status.HTTP_201_CREATED)
def create_role_route(payload: RoleCreate, db: DbSession) -> RoleOut:
    try:
        role = create_role(db, payload)
        db.commit()
        db.refresh(role)
        return role
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/roles", response_model=list[RoleOut])
def list_roles_route(db: DbSession) -> list[RoleOut]:
    return list_roles(db)


@router.post(
    "/invitations", response_model=InvitationOut, status_code=status.HTTP_201_CREATED
)
def create_invitation_route(
    payload: InvitationCreate,
    db: DbSession,
    email_sender: EmailSenderDep,
) -> InvitationOut:
    try:
        invitation, raw_token = create_invitation(
            db, payload=payload, email_sender=email_sender
        )
        db.commit()
        db.refresh(invitation)
        return _serialize_invitation(
            invitation, confirmation_url=f"/confirm/{raw_token}"
        )
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/invitations", response_model=list[InvitationOut])
def list_invitations_route(db: DbSession) -> list[InvitationOut]:
    return [_serialize_invitation(item) for item in list_invitations(db)]


@router.get("/profiles", response_model=list[ProfileOut])
def list_profiles_route(db: DbSession) -> list[ProfileOut]:
    return [_serialize_profile(item) for item in list_profiles(db)]


@router.post("/profiles/{profile_id}/approve", response_model=ProfileOut)
def approve_profile_route(
    profile_id: int, payload: ProfileApproveRequest, db: DbSession
) -> ProfileOut:
    profile = get_profile_by_id(db, profile_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
    try:
        approve_profile(db, profile=profile, payload=payload, actor="admin")
        db.commit()
        db.refresh(profile)
        return _serialize_profile(profile)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/profiles/{profile_id}/reject", response_model=ProfileOut)
def reject_profile_route(profile_id: int, db: DbSession) -> ProfileOut:
    profile = get_profile_by_id(db, profile_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
    reject_profile(db, profile=profile, actor="admin")
    db.commit()
    db.refresh(profile)
    return _serialize_profile(profile)
