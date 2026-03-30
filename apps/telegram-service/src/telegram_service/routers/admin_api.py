import json
import secrets
from datetime import UTC, datetime, timedelta
from urllib.parse import quote_plus

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from telegram_service.auth import hash_password
from telegram_service.database import get_db
from telegram_service.deps import get_current_admin
from telegram_service.managed_secrets import (
    create_or_update_managed_secret,
    deactivate_managed_secret,
    normalize_secret_ref,
)
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
from telegram_service.mtproto import build_client
from telegram_service.schemas import (
    ConnectionCreate,
    ConnectionOut,
    ContextCreate,
    ContextOut,
    ManagedSecretCreate,
    ManagedSecretOut,
    ManagedSecretRotate,
    OnboardingCreateRequest,
    OnboardingOut,
    OnboardingProcessRequest,
    UserCreate,
    UserLoginStartRequest,
    UserLoginVerifyRequest,
    UserOut,
)
from telegram_service.secrets import resolve_secret, upsert_secret
from telegram_service.telegram_client import get_me, get_updates

router = APIRouter(prefix="/api/admin", tags=["admin-api"])
pending_user_logins: dict[int, dict] = {}


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


def _audit(
    db: Session,
    actor: str,
    action: str,
    target_type: str,
    target_id: str,
    details: dict | None = None,
) -> None:
    db.add(
        AuditLog(
            actor=actor,
            action=action,
            target_type=target_type,
            target_id=target_id,
            details=json.dumps(details or {}, ensure_ascii=True),
        )
    )


@router.get("/users", response_model=list[UserOut])
def list_users(
    _: User = Depends(get_current_admin), db: Session = Depends(get_db)
) -> list[User]:
    return db.query(User).order_by(User.id.asc()).all()


@router.post("/users", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def create_user(
    payload: UserCreate,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
) -> User:
    existing = db.query(User).filter(User.username == payload.username).first()
    if existing:
        raise HTTPException(status_code=409, detail="User already exists")

    user = User(
        username=payload.username,
        password_hash=hash_password(payload.password),
        is_admin=payload.is_admin,
        is_active=True,
    )
    db.add(user)
    db.flush()
    _audit(
        db,
        admin.username,
        "create_user",
        "user",
        str(user.id),
        {"username": user.username, "is_admin": user.is_admin},
    )
    db.commit()
    db.refresh(user)
    return user


@router.get("/connections", response_model=list[ConnectionOut])
def list_connections(
    include_inactive: bool = Query(default=False),
    _: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
) -> list[TelegramConnection]:
    query = db.query(TelegramConnection)
    if not include_inactive:
        query = query.filter(TelegramConnection.is_active == True)  # noqa: E712
    return query.order_by(TelegramConnection.id.asc()).all()


@router.delete("/connections/{connection_id}")
def delete_connection(
    connection_id: int,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
) -> dict:
    connection = (
        db.query(TelegramConnection)
        .filter(TelegramConnection.id == connection_id)
        .first()
    )
    if not connection:
        raise HTTPException(status_code=404, detail="Connection not found")
    if not connection.is_active:
        raise HTTPException(status_code=400, detail="Connection is inactive")

    connection.is_active = False
    db.add(connection)
    contexts = (
        db.query(MessagingContext)
        .filter(MessagingContext.connection_id == connection_id)
        .all()
    )
    for context in contexts:
        context.is_active = False
        db.add(context)

    _audit(
        db,
        admin.username,
        "deactivate_connection",
        "connection",
        str(connection.id),
        {"contexts_deactivated": len(contexts)},
    )
    db.commit()
    return {"ok": True, "connection_id": connection.id, "is_active": False}


@router.post(
    "/connections", response_model=ConnectionOut, status_code=status.HTTP_201_CREATED
)
def create_connection(
    payload: ConnectionCreate,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
) -> TelegramConnection:
    existing = (
        db.query(TelegramConnection)
        .filter(TelegramConnection.name == payload.name)
        .first()
    )
    data = payload.model_dump()
    data["secret_ref_token"] = normalize_secret_ref(data.get("secret_ref_token"))
    data["secret_ref_session"] = normalize_secret_ref(data.get("secret_ref_session"))

    if existing and existing.is_active:
        raise HTTPException(status_code=409, detail="Connection name already exists")
    if existing and not existing.is_active:
        for key, value in data.items():
            setattr(existing, key, value)
        existing.is_active = True
        db.add(existing)
        db.flush()
        _audit(
            db,
            admin.username,
            "reactivate_connection",
            "connection",
            str(existing.id),
            data,
        )
        db.commit()
        db.refresh(existing)
        return existing

    connection = TelegramConnection(**data)
    db.add(connection)
    db.flush()
    _audit(
        db,
        admin.username,
        "create_connection",
        "connection",
        str(connection.id),
        payload.model_dump(),
    )
    db.commit()
    db.refresh(connection)
    return connection


@router.get("/contexts", response_model=list[ContextOut])
def list_contexts(
    include_inactive: bool = Query(default=False),
    _: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
) -> list[MessagingContext]:
    query = db.query(MessagingContext)
    if not include_inactive:
        query = query.filter(MessagingContext.is_active == True)  # noqa: E712
    return query.order_by(MessagingContext.id.asc()).all()


@router.post(
    "/contexts", response_model=ContextOut, status_code=status.HTTP_201_CREATED
)
def create_context(
    payload: ContextCreate,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
) -> MessagingContext:
    connection = (
        db.query(TelegramConnection)
        .filter(TelegramConnection.id == payload.connection_id)
        .first()
    )
    if not connection:
        raise HTTPException(status_code=404, detail="Connection not found")
    if not connection.is_active:
        raise HTTPException(status_code=400, detail="Connection is inactive")
    if not connection.is_active:
        raise HTTPException(status_code=400, detail="Connection is inactive")

    context = MessagingContext(**payload.model_dump())
    db.add(context)
    db.flush()
    _audit(
        db,
        admin.username,
        "create_context",
        "context",
        str(context.id),
        payload.model_dump(),
    )
    db.commit()
    db.refresh(context)
    return context


@router.get("/audit-logs")
def list_audit_logs(
    _: User = Depends(get_current_admin), db: Session = Depends(get_db)
) -> list[dict[str, str]]:
    logs = db.query(AuditLog).order_by(AuditLog.id.desc()).limit(200).all()
    return [
        {
            "id": str(item.id),
            "actor": item.actor,
            "action": item.action,
            "target_type": item.target_type,
            "target_id": item.target_id,
            "details": item.details or "{}",
            "created_at": item.created_at.isoformat(),
        }
        for item in logs
    ]


@router.get("/secrets", response_model=list[ManagedSecretOut])
def list_managed_secrets(
    include_inactive: bool = Query(default=False),
    _: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
) -> list:
    from telegram_service.models import ManagedSecret

    query = db.query(ManagedSecret)
    if not include_inactive:
        query = query.filter(ManagedSecret.is_active == True)  # noqa: E712
    return query.order_by(ManagedSecret.id.asc()).all()


@router.post(
    "/secrets", response_model=ManagedSecretOut, status_code=status.HTTP_201_CREATED
)
def create_managed_secret(
    payload: ManagedSecretCreate,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    record = create_or_update_managed_secret(
        db,
        name=payload.name,
        value=payload.value,
        secret_type=payload.secret_type,
        description=payload.description,
    )
    _audit(
        db,
        admin.username,
        "upsert_managed_secret",
        "managed_secret",
        record.name,
        {"secret_type": record.secret_type, "version": record.version},
    )
    db.commit()
    db.refresh(record)
    return record


@router.post("/secrets/{name}/rotate", response_model=ManagedSecretOut)
def rotate_managed_secret(
    name: str,
    payload: ManagedSecretRotate,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    record = create_or_update_managed_secret(db, name=name, value=payload.value)
    _audit(
        db,
        admin.username,
        "rotate_managed_secret",
        "managed_secret",
        record.name,
        {"version": record.version},
    )
    db.commit()
    db.refresh(record)
    return record


@router.delete("/secrets/{name}")
def delete_managed_secret(
    name: str,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
) -> dict:
    record = deactivate_managed_secret(db, name=name)
    _audit(
        db,
        admin.username,
        "deactivate_managed_secret",
        "managed_secret",
        record.name,
    )
    db.commit()
    return {"ok": True, "name": record.name, "is_active": False}


@router.post("/secrets/{name}/validate")
def validate_managed_secret(
    name: str,
    _: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
) -> dict:
    try:
        value = resolve_secret(f"managed://{name}", db)
        return {"ok": True, "name": name, "value_length": len(value)}
    except Exception as exc:
        return {"ok": False, "name": name, "error": str(exc)}


@router.post("/connections/{connection_id}/validate")
async def validate_connection(
    connection_id: int,
    _: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
) -> dict:
    connection = (
        db.query(TelegramConnection)
        .filter(TelegramConnection.id == connection_id)
        .first()
    )
    if not connection:
        raise HTTPException(status_code=404, detail="Connection not found")

    results: dict[str, object] = {
        "ok": True,
        "connection_id": connection.id,
        "name": connection.name,
        "type": connection.type.value,
        "is_active": connection.is_active,
        "checks": {},
    }

    if not connection.is_active:
        results["ok"] = False
        results["checks"]["active"] = "inactive"

    if connection.type == ConnectionType.bot:
        if not connection.secret_ref_token:
            results["ok"] = False
            results["checks"]["token_ref"] = "missing"
        else:
            try:
                token = resolve_secret(connection.secret_ref_token, db)
                me = await get_me(token)
                results["checks"]["token_ref"] = "ok"
                results["checks"]["bot_username"] = (me.get("result") or {}).get(
                    "username"
                )
            except Exception as exc:
                results["ok"] = False
                results["checks"]["token_ref"] = f"error: {exc}"
    else:
        if not connection.secret_ref_session:
            results["ok"] = False
            results["checks"]["session_ref"] = "missing"
        else:
            try:
                value = resolve_secret(connection.secret_ref_session, db)
                results["checks"]["session_ref"] = f"ok (len={len(value)})"
            except Exception as exc:
                results["ok"] = False
                results["checks"]["session_ref"] = f"error: {exc}"

    return results


@router.post("/contexts/repair")
def repair_contexts(
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
) -> dict:
    contexts = db.query(MessagingContext).all()
    repaired = 0
    for context in contexts:
        connection = (
            db.query(TelegramConnection)
            .filter(TelegramConnection.id == context.connection_id)
            .first()
        )
        if not connection or not connection.is_active:
            if context.is_active:
                context.is_active = False
                db.add(context)
                repaired += 1

    _audit(
        db,
        admin.username,
        "repair_contexts",
        "context",
        "bulk",
        {"repaired": repaired},
    )
    db.commit()
    return {"ok": True, "repaired": repaired}


@router.get("/onboarding-links", response_model=list[OnboardingOut])
def list_onboarding_links(
    include_completed: bool = Query(default=True),
    _: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
) -> list[OnboardingOut]:
    query = db.query(OnboardingLink)
    if not include_completed:
        query = query.filter(OnboardingLink.status == "pending")
    links = query.order_by(OnboardingLink.id.desc()).limit(300).all()
    connection_map = {
        c.id: c
        for c in db.query(TelegramConnection)
        .filter(TelegramConnection.id.in_([item.connection_id for item in links]))
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
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
) -> OnboardingOut:
    connection = (
        db.query(TelegramConnection)
        .filter(TelegramConnection.id == payload.connection_id)
        .first()
    )
    if not connection:
        raise HTTPException(status_code=404, detail="Connection not found")
    if connection.type != ConnectionType.bot:
        raise HTTPException(
            status_code=400, detail="Onboarding requires a bot connection"
        )
    if not connection.secret_ref_token:
        raise HTTPException(
            status_code=400, detail="Bot connection requires secret_ref_token"
        )

    token = resolve_secret(connection.secret_ref_token, db)
    data = await get_me(token)
    if not data.get("ok"):
        raise HTTPException(status_code=400, detail=f"Telegram getMe failed: {data}")
    bot_username = (data.get("result") or {}).get("username")
    if not bot_username:
        raise HTTPException(status_code=400, detail="Cannot determine bot username")
    connection.bot_username = bot_username
    db.add(connection)

    token_value = secrets.token_urlsafe(18)
    expires_at = datetime.now(UTC) + timedelta(seconds=payload.ttl_seconds)
    link = OnboardingLink(
        token=token_value,
        connection_id=connection.id,
        target_label=(payload.target_label or "").strip() or None,
        status="pending",
        expires_at=expires_at.replace(tzinfo=None),
    )
    db.add(link)
    db.flush()
    _audit(
        db,
        admin.username,
        "create_onboarding_link",
        "onboarding",
        str(link.id),
        {"connection_id": connection.id, "target_label": link.target_label},
    )
    db.commit()
    db.refresh(link)
    return _build_onboarding_payload(link, bot_username)


@router.post("/onboarding-links/process")
async def process_onboarding_updates(
    payload: OnboardingProcessRequest,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
) -> dict:
    connection = (
        db.query(TelegramConnection)
        .filter(TelegramConnection.id == payload.connection_id)
        .first()
    )
    if not connection:
        raise HTTPException(status_code=404, detail="Connection not found")
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
        admin.username,
        "process_onboarding_updates",
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


@router.delete("/onboarding-links/{link_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_onboarding_link(
    link_id: int,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
) -> None:
    link = db.query(OnboardingLink).filter(OnboardingLink.id == link_id).first()
    if not link:
        raise HTTPException(status_code=404, detail="Onboarding link not found")
    db.delete(link)
    _audit(db, admin.username, "delete_onboarding_link", "onboarding", str(link_id))
    db.commit()
    return None


@router.post("/user-logins/start")
async def start_user_login(
    payload: UserLoginStartRequest,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
) -> dict:
    connection = (
        db.query(TelegramConnection)
        .filter(TelegramConnection.id == payload.connection_id)
        .first()
    )
    if not connection:
        raise HTTPException(status_code=404, detail="Connection not found")
    if connection.type.value != "user":
        raise HTTPException(status_code=400, detail="Connection type must be user")
    if not connection.phone_number:
        raise HTTPException(status_code=400, detail="phone_number is required")

    client = build_client()
    await client.connect()
    sent = await client.send_code_request(connection.phone_number)
    pending_user_logins[connection.id] = {
        "client": client,
        "phone": connection.phone_number,
        "phone_code_hash": sent.phone_code_hash,
    }

    _audit(db, admin.username, "start_user_login", "connection", str(connection.id))
    db.commit()
    return {
        "ok": True,
        "connection_id": connection.id,
        "message": "Code sent to Telegram user. Submit it to /api/admin/user-logins/verify.",
    }


@router.post("/user-logins/verify")
async def verify_user_login(
    payload: UserLoginVerifyRequest,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
) -> dict:
    connection = (
        db.query(TelegramConnection)
        .filter(TelegramConnection.id == payload.connection_id)
        .first()
    )
    if not connection:
        raise HTTPException(status_code=404, detail="Connection not found")
    if not connection.secret_ref_session:
        raise HTTPException(status_code=400, detail="secret_ref_session is required")

    state = pending_user_logins.get(connection.id)
    if not state:
        raise HTTPException(
            status_code=400, detail="No pending login for this connection"
        )

    client = state["client"]
    await client.sign_in(
        phone=state["phone"],
        code=payload.code,
        phone_code_hash=state["phone_code_hash"],
        password=payload.password,
    )
    session_string = client.session.save()
    await client.disconnect()
    pending_user_logins.pop(connection.id, None)

    upsert_secret(connection.secret_ref_session, session_string, db)
    _audit(db, admin.username, "verify_user_login", "connection", str(connection.id))
    db.commit()
    return {
        "ok": True,
        "connection_id": connection.id,
        "message": "Telegram session stored in secret backend",
    }
