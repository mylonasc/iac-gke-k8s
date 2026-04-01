import hashlib

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy.orm import Session

from telegram_service.auth import decode_admin_session
from telegram_service.config import get_settings
from telegram_service.database import get_db
from telegram_service.dex import get_dex_verifier
from telegram_service.models import User
from telegram_service.schemas import RuntimePrincipal

settings = get_settings()


def get_current_admin(request: Request, db: Session = Depends(get_db)) -> User:
    cookie = request.cookies.get(settings.admin_cookie_name)
    if not cookie:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing admin session"
        )

    username = decode_admin_session(cookie)
    if not username:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid admin session"
        )

    user = (
        db.query(User)
        .filter(
            User.username == username, User.is_admin == True, User.is_active == True
        )
        .first()
    )  # noqa: E712
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Admin not found"
        )
    return user


def get_runtime_principal(authorization: str = Header(default="")) -> RuntimePrincipal:
    if not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Bearer token is required"
        )

    token = authorization.replace("Bearer ", "", 1).strip()
    verifier = get_dex_verifier()
    return verifier.verify_token(token)


def _runtime_username(subject: str) -> str:
    digest = hashlib.sha256(subject.encode("utf-8")).hexdigest()[:24]
    return f"dex-{digest}"


def get_current_runtime_user(
    principal: RuntimePrincipal = Depends(get_runtime_principal),
    db: Session = Depends(get_db),
) -> User:
    username = _runtime_username(principal.subject)
    user = db.query(User).filter(User.username == username).first()
    if not user:
        user = User(
            username=username,
            password_hash=None,
            is_admin=False,
            is_active=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Runtime user is inactive"
        )
    return user
