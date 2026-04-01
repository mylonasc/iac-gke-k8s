import hashlib
import json
import secrets
from datetime import UTC, datetime, timedelta
from urllib.parse import quote_plus

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from telegram_service.database import get_db
from telegram_service.deps import get_current_runtime_user, get_runtime_principal
from telegram_service.managed_secrets import create_or_update_managed_secret
from telegram_service.models import (
    AuditLog,
    ConnectionType,
    MessagingContext,
    OnboardingLink,
    TelegramConnection,
    User,
)
from telegram_service.onboarding import process_telegram_update_for_onboarding
from telegram_service.onboarding import is_start_command_without_token
from telegram_service.schemas import (
    ConnectionOut,
    ContextOut,
    OnboardingCreateRequest,
    OnboardingOut,
    OnboardingProcessRequest,
    RuntimeIdentity,
    RuntimePrincipal,
    SelfServiceConnectionCreate,
    SelfServiceContextCreate,
)
from telegram_service.secrets import resolve_secret
from telegram_service.telegram_client import get_me, get_updates

router = APIRouter(prefix="/api/self-service", tags=["self-service-api"])


def _audit(
    db: Session,
    principal: RuntimePrincipal,
    action: str,
    target_type: str,
    target_id: str,
    details: dict | None = None,
) -> None:
    actor = principal.email or principal.username or principal.subject
    db.add(
        AuditLog(
            actor=actor,
            action=action,
            target_type=target_type,
            target_id=target_id,
            details=json.dumps(details or {}, ensure_ascii=True),
        )
    )


def _owned_connection_query(db: Session, user: User):
    return db.query(TelegramConnection).filter(
        TelegramConnection.owner_user_id == user.id
    )


def _resolve_owned_connection(
    db: Session, user: User, connection_id: int
) -> TelegramConnection:
    connection = (
        _owned_connection_query(db, user)
        .filter(
            TelegramConnection.id == connection_id, TelegramConnection.is_active == True
        )
        .first()
    )  # noqa: E712
    if not connection:
        raise HTTPException(status_code=404, detail="Owned connection not found")
    return connection


def _build_onboarding_payload(
    link: OnboardingLink, bot_username: str | None
) -> OnboardingOut:
    deep_link = None
    qr_data_url = None
    if bot_username:
        deep_link = f"https://t.me/{bot_username}?start={link.token}"
        qr_data_url = (
            "https://api.qrserver.com/v1/create-qr-code/?size=240x240&data="
            + quote_plus(deep_link)
        )

    return OnboardingOut(
        id=link.id,
        token=link.token,
        connection_id=link.connection_id,
        target_label=link.target_label,
        status=link.status,
        chat_id=link.chat_id,
        telegram_user_id=link.telegram_user_id,
        telegram_username=link.telegram_username,
        context_id=link.context_id,
        expires_at=link.expires_at,
        completed_at=link.completed_at,
        created_at=link.created_at,
        deep_link=deep_link,
        qr_data_url=qr_data_url,
    )


def _managed_secret_name(user_id: int, connection_name: str, kind: str) -> str:
    safe = "".join(
        ch.lower() if ch.isalnum() else "-" for ch in connection_name.strip()
    )
    compact = "-".join(part for part in safe.split("-") if part)[:40] or "connection"
    suffix = hashlib.sha256(connection_name.encode("utf-8")).hexdigest()[:10]
    return f"tenant-u{user_id}-{kind}-{compact}-{suffix}"


@router.get("/me", response_model=RuntimeIdentity)
def whoami(
    principal: RuntimePrincipal = Depends(get_runtime_principal),
    user: User = Depends(get_current_runtime_user),
) -> RuntimeIdentity:
    return RuntimeIdentity(
        user_id=user.id,
        subject=principal.subject,
        username=principal.username,
        email=principal.email,
    )


@router.get("/connections", response_model=list[ConnectionOut])
def list_connections(
    include_inactive: bool = Query(default=False),
    _: RuntimePrincipal = Depends(get_runtime_principal),
    user: User = Depends(get_current_runtime_user),
    db: Session = Depends(get_db),
) -> list[TelegramConnection]:
    query = _owned_connection_query(db, user)
    if not include_inactive:
        query = query.filter(TelegramConnection.is_active == True)  # noqa: E712
    return query.order_by(TelegramConnection.id.asc()).all()


@router.post(
    "/connections", response_model=ConnectionOut, status_code=status.HTTP_201_CREATED
)
async def create_connection(
    payload: SelfServiceConnectionCreate,
    principal: RuntimePrincipal = Depends(get_runtime_principal),
    user: User = Depends(get_current_runtime_user),
    db: Session = Depends(get_db),
) -> TelegramConnection:
    if payload.type == ConnectionType.bot and not payload.bot_token:
        raise HTTPException(
            status_code=400,
            detail="bot_token is required when creating a bot connection",
        )
    if payload.type == ConnectionType.user and not (
        payload.session_string or payload.phone_number
    ):
        raise HTTPException(
            status_code=400,
            detail="Provide session_string or phone_number for a user connection",
        )

    existing = (
        _owned_connection_query(db, user)
        .filter(TelegramConnection.name == payload.name)
        .first()
    )
    if existing and existing.is_active:
        raise HTTPException(
            status_code=409, detail="Owned connection name already exists"
        )

    token_secret_ref = None
    session_secret_ref = None
    if payload.bot_token:
        token_name = _managed_secret_name(user.id, payload.name, "token")
        create_or_update_managed_secret(
            db,
            name=token_name,
            value=payload.bot_token,
            secret_type="bot_token",
            description=f"Tenant bot token for user {user.id}",
        )
        token_secret_ref = f"managed://{token_name}"
    if payload.session_string:
        session_name = _managed_secret_name(user.id, payload.name, "session")
        create_or_update_managed_secret(
            db,
            name=session_name,
            value=payload.session_string,
            secret_type="session",
            description=f"Tenant session for user {user.id}",
        )
        session_secret_ref = f"managed://{session_name}"

    bot_username = payload.bot_username
    if payload.type == ConnectionType.bot and token_secret_ref:
        token = resolve_secret(token_secret_ref, db)
        me = await get_me(token)
        bot_username = bot_username or (me.get("result") or {}).get("username")

    data = {
        "name": payload.name,
        "type": payload.type,
        "owner_user_id": user.id,
        "bot_username": bot_username,
        "phone_number": payload.phone_number,
        "secret_ref_token": token_secret_ref,
        "secret_ref_session": session_secret_ref,
        "webhook_path": None,
    }

    if existing and not existing.is_active:
        for key, value in data.items():
            setattr(existing, key, value)
        existing.is_active = True
        db.add(existing)
        db.flush()
        _audit(
            db, principal, "reactivate_owned_connection", "connection", str(existing.id)
        )
        db.commit()
        db.refresh(existing)
        return existing

    connection = TelegramConnection(**data)
    db.add(connection)
    db.flush()
    _audit(db, principal, "create_owned_connection", "connection", str(connection.id))
    db.commit()
    db.refresh(connection)
    return connection


@router.get("/contexts", response_model=list[ContextOut])
def list_contexts(
    include_inactive: bool = Query(default=False),
    _: RuntimePrincipal = Depends(get_runtime_principal),
    user: User = Depends(get_current_runtime_user),
    db: Session = Depends(get_db),
) -> list[MessagingContext]:
    query = db.query(MessagingContext).join(
        TelegramConnection, TelegramConnection.id == MessagingContext.connection_id
    )
    query = query.filter(TelegramConnection.owner_user_id == user.id)
    if not include_inactive:
        query = query.filter(MessagingContext.is_active == True)  # noqa: E712
    return query.order_by(MessagingContext.id.asc()).all()


@router.post(
    "/contexts", response_model=ContextOut, status_code=status.HTTP_201_CREATED
)
def create_context(
    payload: SelfServiceContextCreate,
    principal: RuntimePrincipal = Depends(get_runtime_principal),
    user: User = Depends(get_current_runtime_user),
    db: Session = Depends(get_db),
) -> MessagingContext:
    connection = _resolve_owned_connection(db, user, payload.connection_id)
    context = MessagingContext(**payload.model_dump())
    db.add(context)
    db.flush()
    _audit(
        db,
        principal,
        "create_owned_context",
        "context",
        str(context.id),
        {"connection_id": connection.id},
    )
    db.commit()
    db.refresh(context)
    return context


@router.get("/onboarding-links", response_model=list[OnboardingOut])
def list_onboarding_links(
    include_completed: bool = Query(default=True),
    _: RuntimePrincipal = Depends(get_runtime_principal),
    user: User = Depends(get_current_runtime_user),
    db: Session = Depends(get_db),
) -> list[OnboardingOut]:
    connection_ids = [item.id for item in _owned_connection_query(db, user).all()]
    if not connection_ids:
        return []

    query = db.query(OnboardingLink).filter(
        OnboardingLink.connection_id.in_(connection_ids)
    )
    if not include_completed:
        query = query.filter(OnboardingLink.status == "pending")
    links = query.order_by(OnboardingLink.id.desc()).limit(300).all()
    connection_map = {
        c.id: c
        for c in _owned_connection_query(db, user)
        .filter(TelegramConnection.id.in_(connection_ids))
        .all()
    }
    return [
        _build_onboarding_payload(
            item,
            connection_map.get(item.connection_id).bot_username
            if connection_map.get(item.connection_id)
            else None,
        )
        for item in links
    ]


@router.post(
    "/onboarding-links",
    response_model=OnboardingOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_onboarding_link(
    payload: OnboardingCreateRequest,
    principal: RuntimePrincipal = Depends(get_runtime_principal),
    user: User = Depends(get_current_runtime_user),
    db: Session = Depends(get_db),
) -> OnboardingOut:
    connection = _resolve_owned_connection(db, user, payload.connection_id)
    if connection.type != ConnectionType.bot:
        raise HTTPException(
            status_code=400, detail="Onboarding requires a bot connection"
        )
    if not connection.secret_ref_token:
        raise HTTPException(status_code=400, detail="Bot connection requires a token")

    token = resolve_secret(connection.secret_ref_token, db)
    data = await get_me(token)
    bot_username = (data.get("result") or {}).get("username")
    if not bot_username:
        raise HTTPException(status_code=400, detail="Cannot determine bot username")
    connection.bot_username = bot_username
    db.add(connection)

    link = OnboardingLink(
        token=secrets.token_urlsafe(18),
        connection_id=connection.id,
        target_label=(payload.target_label or "").strip() or None,
        status="pending",
        expires_at=(datetime.now(UTC) + timedelta(seconds=payload.ttl_seconds)).replace(
            tzinfo=None
        ),
    )
    db.add(link)
    db.flush()
    _audit(db, principal, "create_owned_onboarding_link", "onboarding", str(link.id))
    db.commit()
    db.refresh(link)
    return _build_onboarding_payload(link, bot_username)


@router.post("/onboarding-links/process")
async def process_onboarding_updates(
    payload: OnboardingProcessRequest,
    principal: RuntimePrincipal = Depends(get_runtime_principal),
    user: User = Depends(get_current_runtime_user),
    db: Session = Depends(get_db),
) -> dict:
    connection = _resolve_owned_connection(db, user, payload.connection_id)
    if connection.type != ConnectionType.bot:
        raise HTTPException(
            status_code=400, detail="Only bot connections are supported"
        )
    if not connection.secret_ref_token:
        raise HTTPException(status_code=400, detail="secret_ref_token is required")

    token = resolve_secret(connection.secret_ref_token, db)
    updates = await get_updates(token=token, offset=payload.offset, limit=payload.limit)
    items = updates.get("result") if isinstance(updates, dict) else []
    completed = 0
    start_without_token = 0
    max_update_id: int | None = None
    for item in items or []:
        update_id = item.get("update_id")
        if isinstance(update_id, int):
            max_update_id = (
                update_id if max_update_id is None else max(max_update_id, update_id)
            )

        message = item.get("message") or item.get("edited_message") or {}
        text = str(message.get("text") or "")
        if is_start_command_without_token(text):
            start_without_token += 1

        link = process_telegram_update_for_onboarding(db, connection, item)
        if link:
            completed += 1

    if max_update_id is not None:
        await get_updates(token=token, offset=max_update_id + 1, limit=1)

    _audit(
        db,
        principal,
        "process_owned_onboarding_updates",
        "connection",
        str(connection.id),
        {"processed_updates": len(items or []), "completed": completed},
    )
    db.commit()
    return {
        "ok": True,
        "connection_id": connection.id,
        "processed_updates": len(items or []),
        "completed_onboarding_links": completed,
        "start_without_token_updates": start_without_token,
        "next_offset": (max_update_id + 1)
        if max_update_id is not None
        else payload.offset,
    }
