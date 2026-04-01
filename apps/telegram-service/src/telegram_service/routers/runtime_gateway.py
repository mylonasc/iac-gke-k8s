import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from telegram_service.config import get_settings
from telegram_service.database import get_db
from telegram_service.deps import get_current_runtime_user, get_runtime_principal
from telegram_service.models import (
    ConnectionType,
    ContextMode,
    MessagingContext,
    OtpChallenge,
    TelegramConnection,
    User,
)
from telegram_service.onboarding import process_telegram_update_for_onboarding
from telegram_service.mtproto import get_user_messages, send_user_message
from telegram_service.schemas import (
    OtpIssueRequest,
    OtpIssueResponse,
    OtpVerifyRequest,
    OtpVerifyResponse,
    RuntimePrincipal,
    SendMessageRequest,
)
from telegram_service.secrets import resolve_secret
from telegram_service.telegram_client import get_updates, send_message

router = APIRouter(prefix="/gateway", tags=["runtime-gateway"])
settings = get_settings()


def _resolve_context(
    db: Session, context_id: int, user: User
) -> tuple[MessagingContext, TelegramConnection]:
    context = (
        db.query(MessagingContext)
        .filter(MessagingContext.id == context_id, MessagingContext.is_active == True)
        .first()
    )  # noqa: E712
    if not context:
        raise HTTPException(status_code=404, detail="Context not found")

    connection = (
        db.query(TelegramConnection)
        .filter(
            TelegramConnection.id == context.connection_id,
            TelegramConnection.is_active == True,
        )
        .first()
    )  # noqa: E712
    if not connection:
        raise HTTPException(status_code=404, detail="Connection not found")

    if connection.owner_user_id != user.id:
        raise HTTPException(status_code=404, detail="Owned context not found")

    return context, connection


def _ensure_send_allowed(context: MessagingContext) -> None:
    if context.mode == ContextMode.receive_only:
        raise HTTPException(status_code=403, detail="Context is receive_only")


def _ensure_receive_allowed(context: MessagingContext) -> None:
    if context.mode == ContextMode.send_only:
        raise HTTPException(status_code=403, detail="Context is send_only")


def _hash_otp(challenge_id: str, code: str) -> str:
    payload = f"{challenge_id}:{code}:{settings.admin_session_secret}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _generate_otp(length: int) -> str:
    alphabet = "0123456789"
    return "".join(secrets.choice(alphabet) for _ in range(length))


def _filter_bot_updates_for_chat(
    provider_response: dict[str, Any], chat_id: str
) -> list[dict[str, Any]]:
    results = (
        provider_response.get("result") if isinstance(provider_response, dict) else []
    )
    filtered: list[dict[str, Any]] = []
    for item in results or []:
        message = item.get("message") or item.get("edited_message") or {}
        item_chat_id = str(((message.get("chat") or {}).get("id", ""))).strip()
        if item_chat_id == chat_id:
            filtered.append(item)
    return filtered


async def _send_through_connection(
    connection: TelegramConnection, chat_id: str, text: str, db: Session
) -> dict[str, Any]:
    if connection.type == ConnectionType.bot:
        if not connection.secret_ref_token:
            raise HTTPException(
                status_code=400, detail="Connection token secret_ref is missing"
            )
        try:
            token = resolve_secret(connection.secret_ref_token, db)
        except Exception as exc:
            raise HTTPException(
                status_code=500, detail=f"Cannot resolve bot token: {exc}"
            ) from exc
        provider_response = await send_message(token=token, chat_id=chat_id, text=text)
        return {"connection_type": "bot", "provider_response": provider_response}

    if connection.type == ConnectionType.user:
        if not connection.secret_ref_session:
            raise HTTPException(
                status_code=400, detail="Connection session secret_ref is missing"
            )
        try:
            session_string = resolve_secret(connection.secret_ref_session, db)
        except Exception as exc:
            raise HTTPException(
                status_code=500, detail=f"Cannot resolve user session secret: {exc}"
            ) from exc

        provider_response = await send_user_message(
            session_string=session_string, chat_id=chat_id, text=text
        )
        return {"connection_type": "user", "provider_response": provider_response}

    raise HTTPException(status_code=400, detail="Unsupported connection type")


async def _receive_through_connection(
    connection: TelegramConnection, chat_id: str, offset: int | None, db: Session
) -> dict[str, Any]:
    if connection.type == ConnectionType.bot:
        if not connection.secret_ref_token:
            raise HTTPException(
                status_code=400, detail="Connection token secret_ref is missing"
            )
        try:
            token = resolve_secret(connection.secret_ref_token, db)
        except Exception as exc:
            raise HTTPException(
                status_code=500, detail=f"Cannot resolve bot token: {exc}"
            ) from exc
        provider_response = await get_updates(token=token, offset=offset)
        filtered = _filter_bot_updates_for_chat(provider_response, chat_id)

        return {
            "connection_type": "bot",
            "provider_response": {
                "ok": provider_response.get("ok", True),
                "result": filtered,
            },
        }

    if connection.type == ConnectionType.user:
        if not connection.secret_ref_session:
            raise HTTPException(
                status_code=400, detail="Connection session secret_ref is missing"
            )
        try:
            session_string = resolve_secret(connection.secret_ref_session, db)
        except Exception as exc:
            raise HTTPException(
                status_code=500, detail=f"Cannot resolve user session secret: {exc}"
            ) from exc

        provider_response = await get_user_messages(
            session_string=session_string,
            chat_id=chat_id,
            min_id=offset,
            limit=20,
        )
        return {"connection_type": "user", "provider_response": provider_response}

    raise HTTPException(status_code=400, detail="Unsupported connection type")


@router.get("/whoami")
def whoami(
    principal: RuntimePrincipal = Depends(get_runtime_principal),
) -> RuntimePrincipal:
    return principal


@router.post("/contexts/{context_id}/send")
async def send_to_context(
    context_id: int,
    payload: SendMessageRequest,
    _: RuntimePrincipal = Depends(get_runtime_principal),
    user: User = Depends(get_current_runtime_user),
    db: Session = Depends(get_db),
) -> dict:
    context, connection = _resolve_context(db, context_id, user)
    _ensure_send_allowed(context)
    response = await _send_through_connection(
        connection, chat_id=context.chat_id, text=payload.text, db=db
    )
    return {"ok": True, "context_id": context.id, **response}


@router.get("/contexts/{context_id}/updates")
async def get_context_updates(
    context_id: int,
    offset: int | None = Query(default=None),
    _: RuntimePrincipal = Depends(get_runtime_principal),
    user: User = Depends(get_current_runtime_user),
    db: Session = Depends(get_db),
) -> dict:
    context, connection = _resolve_context(db, context_id, user)
    _ensure_receive_allowed(context)
    response = await _receive_through_connection(
        connection, chat_id=context.chat_id, offset=offset, db=db
    )
    return {"ok": True, "context_id": context.id, **response}


@router.post("/otp/issue", response_model=OtpIssueResponse)
async def issue_otp(
    payload: OtpIssueRequest,
    principal: RuntimePrincipal = Depends(get_runtime_principal),
    user: User = Depends(get_current_runtime_user),
    db: Session = Depends(get_db),
) -> OtpIssueResponse:
    context, connection = _resolve_context(db, payload.context_id, user)
    _ensure_send_allowed(context)

    otp_code = _generate_otp(payload.length)
    challenge_id = secrets.token_urlsafe(18)
    expires_at = datetime.now(UTC) + timedelta(seconds=payload.ttl_seconds)
    otp_message = (
        f"Your OTP is {otp_code}. It expires in {payload.ttl_seconds // 60} minute(s)."
    )
    if payload.purpose:
        otp_message = f"[{payload.purpose}] {otp_message}"

    await _send_through_connection(
        connection, chat_id=context.chat_id, text=otp_message, db=db
    )

    record = OtpChallenge(
        challenge_id=challenge_id,
        context_id=context.id,
        principal_subject=principal.subject,
        target_label=(payload.target_label or "").strip() or None,
        purpose=(payload.purpose or "auth").strip() or "auth",
        otp_hash=_hash_otp(challenge_id, otp_code),
        expires_at=expires_at.replace(tzinfo=None),
        attempts=0,
        max_attempts=5,
    )
    db.add(record)
    db.commit()

    return OtpIssueResponse(
        ok=True,
        challenge_id=challenge_id,
        expires_at=expires_at,
        context_id=context.id,
    )


@router.post("/otp/verify", response_model=OtpVerifyResponse)
def verify_otp(
    payload: OtpVerifyRequest,
    principal: RuntimePrincipal = Depends(get_runtime_principal),
    db: Session = Depends(get_db),
) -> OtpVerifyResponse:
    record = (
        db.query(OtpChallenge)
        .filter(OtpChallenge.challenge_id == payload.challenge_id)
        .first()
    )
    if not record:
        return OtpVerifyResponse(ok=True, valid=False, reason="challenge_not_found")

    if record.principal_subject != principal.subject:
        return OtpVerifyResponse(
            ok=True, valid=False, reason="challenge_owner_mismatch"
        )

    if record.consumed_at is not None:
        return OtpVerifyResponse(ok=True, valid=False, reason="already_consumed")

    now = datetime.now(UTC).replace(tzinfo=None)
    if record.expires_at <= now:
        return OtpVerifyResponse(ok=True, valid=False, reason="expired")

    if record.attempts >= record.max_attempts:
        return OtpVerifyResponse(ok=True, valid=False, reason="attempts_exceeded")

    candidate_hash = _hash_otp(payload.challenge_id, payload.code)
    if candidate_hash != record.otp_hash:
        record.attempts += 1
        db.add(record)
        db.commit()
        return OtpVerifyResponse(ok=True, valid=False, reason="invalid_code")

    record.consumed_at = now
    db.add(record)
    db.commit()
    return OtpVerifyResponse(ok=True, valid=True)


@router.post("/webhook/{connection_name}")
async def receive_webhook(
    connection_name: str, request: Request, db: Session = Depends(get_db)
) -> dict:
    expected_secret = settings.webhook_shared_secret.strip()
    if expected_secret:
        actual_secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if actual_secret != expected_secret:
            raise HTTPException(status_code=401, detail="Invalid webhook secret")

    connection = (
        db.query(TelegramConnection)
        .filter(
            TelegramConnection.name == connection_name,
            TelegramConnection.is_active == True,
        )
        .first()
    )  # noqa: E712
    if not connection:
        raise HTTPException(status_code=404, detail="Connection not found")

    payload = await request.json()
    completed = 0
    if connection.type == ConnectionType.bot and isinstance(payload, dict):
        link = process_telegram_update_for_onboarding(db, connection, payload)
        if link:
            completed = 1
            db.commit()
    return {
        "ok": True,
        "message": "Webhook accepted",
        "connection": connection.name,
        "event_type": list(payload.keys())[0] if payload else "unknown",
        "onboarding_completed": completed,
    }
