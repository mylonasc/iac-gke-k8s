from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from telegram_service.database import get_db
from telegram_service.deps import get_current_admin
from telegram_service.managed_secrets import normalize_secret_ref
from telegram_service.models import MessagingContext, TelegramConnection, User
from telegram_service.schemas import (
    ConnectionCreate,
    ConnectionOut,
    ContextCreate,
    ContextOut,
)

router = APIRouter(prefix="/api/config", tags=["config-api"])


@router.get("/connections", response_model=list[ConnectionOut])
def list_connections(
    _: User = Depends(get_current_admin), db: Session = Depends(get_db)
) -> list[TelegramConnection]:
    return db.query(TelegramConnection).order_by(TelegramConnection.id.asc()).all()


@router.post(
    "/connections", response_model=ConnectionOut, status_code=status.HTTP_201_CREATED
)
def create_connection(
    payload: ConnectionCreate,
    _: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
) -> TelegramConnection:
    existing = (
        db.query(TelegramConnection)
        .filter(TelegramConnection.name == payload.name)
        .first()
    )
    if existing:
        raise HTTPException(status_code=409, detail="Connection name already exists")

    data = payload.model_dump()
    data["secret_ref_token"] = normalize_secret_ref(data.get("secret_ref_token"))
    data["secret_ref_session"] = normalize_secret_ref(data.get("secret_ref_session"))
    connection = TelegramConnection(**data)
    db.add(connection)
    db.commit()
    db.refresh(connection)
    return connection


@router.post(
    "/contexts", response_model=ContextOut, status_code=status.HTTP_201_CREATED
)
def create_context(
    payload: ContextCreate,
    _: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
) -> MessagingContext:
    connection = (
        db.query(TelegramConnection)
        .filter(TelegramConnection.id == payload.connection_id)
        .first()
    )
    if not connection:
        raise HTTPException(status_code=404, detail="Connection not found")

    context = MessagingContext(**payload.model_dump())
    db.add(context)
    db.commit()
    db.refresh(context)
    return context
