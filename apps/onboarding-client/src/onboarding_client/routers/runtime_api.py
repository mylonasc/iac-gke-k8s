from fastapi import APIRouter

from onboarding_client.deps import CurrentPrincipal, DbSession
from onboarding_client.schemas import RuntimeIdentity, RuntimeRolesOut
from onboarding_client.services.profiles import (
    get_active_role_slugs,
    resolve_profile_for_principal,
)

router = APIRouter(prefix="/api/runtime", tags=["runtime-api"])


@router.get("/me", response_model=RuntimeIdentity)
def runtime_me(principal: CurrentPrincipal, db: DbSession) -> RuntimeIdentity:
    profile = resolve_profile_for_principal(db, principal)
    db.commit()
    return RuntimeIdentity(
        subject=principal.subject,
        email=principal.email,
        username=principal.username,
        profile_status=profile.status if profile else None,
    )


@router.get("/me/roles", response_model=RuntimeRolesOut)
def runtime_roles(principal: CurrentPrincipal, db: DbSession) -> RuntimeRolesOut:
    profile = resolve_profile_for_principal(db, principal)
    db.commit()
    return RuntimeRolesOut(
        subject=principal.subject,
        email=principal.email,
        roles=get_active_role_slugs(profile),
    )
