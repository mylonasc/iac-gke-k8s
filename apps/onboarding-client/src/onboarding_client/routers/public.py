from fastapi import APIRouter, Form, HTTPException
from fastapi.responses import HTMLResponse

from onboarding_client.deps import DbSession
from onboarding_client.services.invitations import (
    confirm_invitation,
    get_invitation_by_token,
)
from onboarding_client.services.profiles import submit_profile

router = APIRouter(tags=["public"])


def _page(title: str, body: str) -> HTMLResponse:
    return HTMLResponse(
        f"<!doctype html><html><head><title>{title}</title></head><body><h1>{title}</h1>{body}</body></html>"
    )


def _profile_form(token: str, email: str) -> str:
    return (
        f"<p>Invitation for <strong>{email}</strong></p>"
        f'<form method="post" action="/profile/{token}">'
        '<label>Full name <input type="text" name="full_name" required></label><br>'
        '<label>Username <input type="text" name="username"></label><br>'
        '<label>Organization <input type="text" name="organization"></label><br>'
        '<label>Team <input type="text" name="team"></label><br>'
        '<label>Justification <textarea name="justification"></textarea></label><br>'
        '<button type="submit">Submit profile</button>'
        "</form>"
    )


@router.get("/")
def root() -> HTMLResponse:
    return _page(
        "Onboarding Client", "<p>Use an invitation link to start onboarding.</p>"
    )


@router.get("/confirm/{token}")
def confirm_invitation_page(token: str, db: DbSession) -> HTMLResponse:
    try:
        invitation = confirm_invitation(db, token)
        db.commit()
        return _page("Confirm Invitation", _profile_form(token, invitation.email))
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/confirm/{token}")
def confirm_invitation_post(token: str, db: DbSession) -> HTMLResponse:
    return confirm_invitation_page(token, db)


@router.get("/profile/{token}")
def profile_form(token: str, db: DbSession) -> HTMLResponse:
    try:
        invitation, _ = get_invitation_by_token(db, token)
        return _page("Profile Form", _profile_form(token, invitation.email))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/profile/{token}")
def submit_profile_route(
    token: str,
    db: DbSession,
    full_name: str = Form(),
    username: str | None = Form(default=None),
    organization: str | None = Form(default=None),
    team: str | None = Form(default=None),
    justification: str | None = Form(default=None),
) -> HTMLResponse:
    try:
        profile = submit_profile(
            db,
            raw_token=token,
            username=username,
            full_name=full_name,
            organization=organization,
            team=team,
            justification=justification,
        )
        db.commit()
        return _page(
            "Profile Submitted",
            f"<p>Thanks {profile.full_name}, your profile is pending admin approval.</p>",
        )
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
