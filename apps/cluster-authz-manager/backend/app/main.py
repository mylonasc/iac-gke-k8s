from fastapi import FastAPI, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from typing import List, Optional
from .models.base import engine, Base, get_db, SessionLocal
from .services.bootstrap import bootstrap_sra_profile, bootstrap_manager_profile
from .services.policy_compiler import PolicyCompiler
from .services.authz import require_permission
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

@app.middleware("http")
async def discover_user_middleware(request: Request, call_next):
    subject = request.headers.get("x-auth-request-user")
    email = request.headers.get("x-auth-request-email")
    
    if subject:
        db = SessionLocal()
        try:
            user = db.query(models.KnownUser).filter(models.KnownUser.subject == subject).first()
            if not user:
                user = models.KnownUser(subject=subject, email=email)
                db.add(user)
            else:
                if email: user.email = email
            db.commit()
        finally:
            db.close()
            
    return await call_next(request)

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
    user = models.KnownUser(**user_in.dict())
    db.add(user)
    db.commit()
    db.refresh(user)
    return user

@app.patch("/api/users/{user_id}", response_model=schemas.KnownUser, dependencies=[Depends(require_permission("cluster-auth-admin"))])
def update_user(user_id: str, user_in: schemas.KnownUserUpdate, db: Session = Depends(get_db)):
    user = db.query(models.KnownUser).filter(models.KnownUser.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    update_data = user_in.dict(exclude_unset=True)
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
