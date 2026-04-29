from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import UTC, datetime
import hmac
import os
from pydantic import BaseModel
from .models.base import engine, Base, get_db, SessionLocal
from .services.bootstrap import bootstrap_sra_profile, bootstrap_manager_profile
from .services.policy_compiler import PolicyCompiler
from .services.authz import require_permission
from .auth import AuthConfig, TokenVerifier, authenticate_request
from .routers import apps
from .models import authz as models
from .schemas import authz as schemas

from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Ensure tables are created
    Base.metadata.create_all(bind=engine)
    
    # Manual migration for SQLite as create_all doesn't add columns to existing tables
    from sqlalchemy import text
    db = SessionLocal()
    try:
        # Check and add missing columns to known_users
        columns = [c[1] for c in db.execute(text("PRAGMA table_info(known_users)")).fetchall()]
        if "is_active" not in columns:
            db.execute(text("ALTER TABLE known_users ADD COLUMN is_active BOOLEAN DEFAULT 1"))
        if "notes" not in columns:
            db.execute(text("ALTER TABLE known_users ADD COLUMN notes VARCHAR"))
        if "created_at" not in columns:
            db.execute(text("ALTER TABLE known_users ADD COLUMN created_at DATETIME"))
        db.commit()
        
        bootstrap_sra_profile(db)
        bootstrap_manager_profile(db)
    finally:
        db.close()
    yield

app = FastAPI(title="Cluster Authz Manager", lifespan=lifespan)
auth_config = AuthConfig.from_env()
token_verifier = TokenVerifier(auth_config)


def _normalize_identity(subject: str | None, email: str | None) -> tuple[str, str | None]:
    normalized_subject = (subject or "").strip()
    normalized_email = (email or "").strip().lower() or None
    if normalized_subject:
        return normalized_subject, normalized_email
    if normalized_email:
        return f"email:{normalized_email}", normalized_email
    raise ValueError("subject or email is required")


def _upsert_known_user(
    db: Session,
    *,
    subject: str | None,
    email: str | None,
    display_name: str | None = None,
) -> models.KnownUser:
    normalized_subject, normalized_email = _normalize_identity(subject, email)
    normalized_display_name = (display_name or "").strip() or None

    user = (
        db.query(models.KnownUser)
        .filter(models.KnownUser.subject == normalized_subject)
        .first()
    )
    if not user and normalized_email:
        user = (
            db.query(models.KnownUser)
            .filter(models.KnownUser.email == normalized_email)
            .order_by(models.KnownUser.last_seen_at.desc())
            .first()
        )

    if not user:
        user = models.KnownUser(
            subject=normalized_subject,
            email=normalized_email,
            display_name=normalized_display_name,
        )
        db.add(user)
    else:
        if normalized_email:
            user.email = normalized_email
        if normalized_display_name:
            user.display_name = normalized_display_name
        if user.subject.startswith("email:") and not normalized_subject.startswith("email:"):
            user.subject = normalized_subject
        user.last_seen_at = datetime.now(UTC)

    db.commit()
    db.refresh(user)
    return user


def _verify_known_user_sync_token(request: Request) -> None:
    expected_token = (os.getenv("KNOWN_USER_SYNC_TOKEN") or "").strip()
    if not expected_token:
        return
    provided_token = (request.headers.get("x-known-user-sync-token") or "").strip()
    if not provided_token or not hmac.compare_digest(provided_token, expected_token):
        raise HTTPException(status_code=403, detail="Invalid known-user sync token")


class KnownUserSyncRequest(BaseModel):
    subject: Optional[str] = None
    email: Optional[str] = None
    display_name: Optional[str] = None

@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    try:
        await authenticate_request(
            request,
            config=auth_config,
            verifier=token_verifier,
        )
    except HTTPException as exc:
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
    return await call_next(request)


@app.middleware("http")
async def discover_user_middleware(request: Request, call_next):
    subject = str(getattr(request.state, "auth_subject", "") or "").strip()
    email = str(getattr(request.state, "auth_email", "") or "").strip() or None
    if not subject and not email:
        subject = request.headers.get("x-auth-request-user")
        email = request.headers.get("x-auth-request-email")
    
    if subject or email:
        db = SessionLocal()
        try:
            _upsert_known_user(db, subject=subject, email=email)
        except ValueError:
            pass
        finally:
            db.close()
            
    return await call_next(request)


@app.post("/api/internal/discover-user")
def sync_known_user(payload: KnownUserSyncRequest, request: Request):
    _verify_known_user_sync_token(request)
    db = SessionLocal()
    try:
        try:
            user = _upsert_known_user(
                db,
                subject=payload.subject,
                email=payload.email,
                display_name=payload.display_name,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "id": user.id,
            "subject": user.subject,
            "email": user.email,
            "display_name": user.display_name,
            "last_seen_at": user.last_seen_at,
        }
    finally:
        db.close()

@app.get("/health")
def health():
    return {"status": "ok"}

app.include_router(
    apps.router, 
    dependencies=[Depends(require_permission("cluster-auth-admin"))]
)

@app.get("/api/users", response_model=List[schemas.KnownUser], dependencies=[Depends(require_permission("cluster-auth-admin"))])
def list_known_users(q: Optional[str] = None, db: Session = Depends(get_db)):
    query = db.query(models.KnownUser)
    if q:
        query = query.filter(
            (models.KnownUser.email.ilike(f"%{q}%")) | 
            (models.KnownUser.subject.ilike(f"%{q}%")) |
            (models.KnownUser.display_name.ilike(f"%{q}%"))
        )
    return query.order_by(models.KnownUser.last_seen_at.desc()).all()

@app.post("/api/users", response_model=schemas.KnownUser, dependencies=[Depends(require_permission("cluster-auth-admin"))])
def create_user(user_in: schemas.KnownUserCreate, db: Session = Depends(get_db)):
    existing = db.query(models.KnownUser).filter(models.KnownUser.subject == user_in.subject).first()
    if existing:
        raise HTTPException(status_code=400, detail="User with this subject already exists")
    user = models.KnownUser(**user_in.model_dump())
    db.add(user)
    db.commit()
    db.refresh(user)
    return user

@app.patch("/api/users/{user_id}", response_model=schemas.KnownUser, dependencies=[Depends(require_permission("cluster-auth-admin"))])
def update_user(user_id: str, user_in: schemas.KnownUserUpdate, db: Session = Depends(get_db)):
    user = db.query(models.KnownUser).filter(models.KnownUser.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    update_data = user_in.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(user, field, value)
        
    db.commit()
    db.refresh(user)
    return user

@app.delete("/api/users/{user_id}", dependencies=[Depends(require_permission("cluster-auth-admin"))])
def delete_user(user_id: str, db: Session = Depends(get_db)):
    user = db.query(models.KnownUser).filter(models.KnownUser.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    db.delete(user)
    db.commit()
    return {"status": "deleted"}

@app.get("/api/apps/{app_slug}/policy/current")
def get_app_policy(app_slug: str, db: Session = Depends(get_db)):
    try:
        return PolicyCompiler.compile_to_sra_yaml(db, app_slug)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
