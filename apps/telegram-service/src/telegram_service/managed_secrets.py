import base64
import hashlib

from cryptography.fernet import Fernet
from fastapi import HTTPException
from sqlalchemy.orm import Session

from telegram_service.config import get_settings
from telegram_service.models import ManagedSecret

settings = get_settings()


def _build_fernet() -> Fernet:
    material = (
        settings.gateway_secret_master_key.strip() or settings.admin_session_secret
    )
    digest = hashlib.sha256(material.encode("utf-8")).digest()
    key = base64.urlsafe_b64encode(digest)
    return Fernet(key)


fernet = _build_fernet()


def normalize_secret_ref(secret_ref: str | None) -> str | None:
    if not secret_ref:
        return None
    value = secret_ref.strip()
    if not value:
        return None
    if "://" in value:
        return value
    return f"managed://{value}"


def create_or_update_managed_secret(
    db: Session,
    name: str,
    value: str,
    secret_type: str = "generic",
    description: str | None = None,
) -> ManagedSecret:
    existing = db.query(ManagedSecret).filter(ManagedSecret.name == name).first()
    encrypted = fernet.encrypt(value.encode("utf-8")).decode("utf-8")
    if existing:
        existing.encrypted_value = encrypted
        existing.version += 1
        existing.secret_type = secret_type
        existing.description = description
        existing.is_active = True
        db.add(existing)
        db.flush()
        return existing

    record = ManagedSecret(
        name=name,
        encrypted_value=encrypted,
        secret_type=secret_type,
        description=description,
        version=1,
        is_active=True,
    )
    db.add(record)
    db.flush()
    return record


def deactivate_managed_secret(db: Session, name: str) -> ManagedSecret:
    record = db.query(ManagedSecret).filter(ManagedSecret.name == name).first()
    if not record:
        raise HTTPException(status_code=404, detail="Managed secret not found")
    record.is_active = False
    db.add(record)
    db.flush()
    return record


def resolve_managed_secret(db: Session, name: str) -> str:
    record = (
        db.query(ManagedSecret)
        .filter(ManagedSecret.name == name, ManagedSecret.is_active == True)
        .first()
    )  # noqa: E712
    if not record:
        raise RuntimeError(f"Managed secret '{name}' not found or inactive")
    return fernet.decrypt(record.encrypted_value.encode("utf-8")).decode("utf-8")
