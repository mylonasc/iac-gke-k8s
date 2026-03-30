from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
import httpx
import secrets
from datetime import UTC, datetime, timedelta
from urllib.parse import quote_plus
from sqlalchemy.orm import Session

from telegram_service.auth import create_admin_session, verify_password
from telegram_service.config import get_settings
from telegram_service.database import get_db
from telegram_service.deps import get_current_admin
from telegram_service.managed_secrets import (
    create_or_update_managed_secret,
    deactivate_managed_secret,
    normalize_secret_ref,
)
from telegram_service.models import (
    ConnectionType,
    ContextMode,
    ManagedSecret,
    MessagingContext,
    OnboardingLink,
    TelegramConnection,
    User,
)
from telegram_service.onboarding import process_telegram_update_for_onboarding
from telegram_service.onboarding import is_start_command_without_token
from telegram_service.secrets import resolve_secret
from telegram_service.telegram_client import get_me, get_updates

templates = Jinja2Templates(directory="src/telegram_service/templates")
router = APIRouter(tags=["admin-ui"])
settings = get_settings()


def _render_onboarding(
    request: Request,
    admin: User,
    db: Session,
    result: str = "",
    error: str = "",
) -> HTMLResponse:
    bot_connections = (
        db.query(TelegramConnection)
        .filter(TelegramConnection.type == ConnectionType.bot)
        .order_by(TelegramConnection.id.asc())
        .all()
    )
    links = db.query(OnboardingLink).order_by(OnboardingLink.id.desc()).limit(200).all()
    connection_map = {item.id: item for item in bot_connections}
    onboarding_rows = []
    for item in links:
        conn = connection_map.get(item.connection_id)
        bot_username = conn.bot_username if conn else None
        deep_link = (
            f"https://t.me/{bot_username}?start={item.token}" if bot_username else None
        )
        qr_data_url = (
            "https://api.qrserver.com/v1/create-qr-code/?size=220x220&data="
            + quote_plus(deep_link)
            if deep_link
            else None
        )
        onboarding_rows.append(
            {
                "id": item.id,
                "connection_id": item.connection_id,
                "target_label": item.target_label,
                "status": item.status,
                "chat_id": item.chat_id,
                "context_id": item.context_id,
                "expires_at": item.expires_at,
                "created_at": item.created_at,
                "deep_link": deep_link,
                "qr_data_url": qr_data_url,
            }
        )

    return templates.TemplateResponse(
        request=request,
        name="onboarding.html",
        context={
            "admin": admin,
            "bot_connections": bot_connections,
            "onboarding_rows": onboarding_rows,
            "result": result,
            "error": error,
        },
    )


def _render_dashboard(
    request: Request,
    admin: User,
    db: Session,
    runtime_result: str = "",
    runtime_error: str = "",
) -> HTMLResponse:
    users = db.query(User).order_by(User.id.asc()).all()
    connections = (
        db.query(TelegramConnection).order_by(TelegramConnection.id.asc()).all()
    )
    contexts = db.query(MessagingContext).order_by(MessagingContext.id.asc()).all()
    managed_secrets = db.query(ManagedSecret).order_by(ManagedSecret.id.asc()).all()
    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={
            "admin": admin,
            "users": users,
            "connections": connections,
            "contexts": contexts,
            "managed_secrets": managed_secrets,
            "runtime_result": runtime_result,
            "runtime_error": runtime_error,
        },
    )


@router.get("/admin/login", response_class=HTMLResponse)
def login_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request, name="login.html", context={"error": ""}
    )


@router.post("/admin/login", response_class=HTMLResponse)
def login_submit(
    request: Request,
    username: str = Form(),
    password: str = Form(),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    user = (
        db.query(User)
        .filter(
            User.username == username, User.is_admin == True, User.is_active == True
        )
        .first()
    )  # noqa: E712
    if (
        not user
        or not user.password_hash
        or not verify_password(password, user.password_hash)
    ):
        return templates.TemplateResponse(
            request=request,
            name="login.html",
            context={"error": "Invalid username or password"},
            status_code=status.HTTP_401_UNAUTHORIZED,
        )

    response = RedirectResponse(url="/admin", status_code=status.HTTP_303_SEE_OTHER)
    response.set_cookie(
        key=settings.admin_cookie_name,
        value=create_admin_session(user.username),
        httponly=True,
        samesite="lax",
    )
    return response


@router.get("/admin/logout")
def logout() -> RedirectResponse:
    response = RedirectResponse(
        url="/admin/login", status_code=status.HTTP_303_SEE_OTHER
    )
    response.delete_cookie(settings.admin_cookie_name)
    return response


@router.get("/admin", response_class=HTMLResponse)
def dashboard(
    request: Request,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    return _render_dashboard(request=request, admin=admin, db=db)


@router.get("/admin/onboarding", response_class=HTMLResponse)
def onboarding_tab(
    request: Request,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    return _render_onboarding(request=request, admin=admin, db=db)


@router.post("/admin/connections")
def create_connection_from_ui(
    name: str = Form(),
    type: str = Form(),
    secret_ref_token: str = Form(default=""),
    secret_ref_session: str = Form(default=""),
    phone_number: str = Form(default=""),
    _: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    exists = (
        db.query(TelegramConnection).filter(TelegramConnection.name == name).first()
    )
    token_ref = normalize_secret_ref(secret_ref_token)
    session_ref = normalize_secret_ref(secret_ref_session)

    if exists and exists.is_active:
        raise HTTPException(status_code=409, detail="Connection already exists")
    if exists and not exists.is_active:
        exists.type = ConnectionType(type)
        exists.secret_ref_token = token_ref
        exists.secret_ref_session = session_ref
        exists.phone_number = phone_number or None
        exists.is_active = True
        db.add(exists)
        db.commit()
        return RedirectResponse(url="/admin", status_code=status.HTTP_303_SEE_OTHER)

    connection = TelegramConnection(
        name=name,
        type=ConnectionType(type),
        secret_ref_token=token_ref,
        secret_ref_session=session_ref,
        phone_number=phone_number or None,
    )
    db.add(connection)
    db.commit()
    return RedirectResponse(url="/admin", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/admin/contexts")
def create_context_from_ui(
    connection_id: int = Form(),
    name: str = Form(),
    mode: str = Form(),
    chat_id: str = Form(),
    _: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    connection = (
        db.query(TelegramConnection)
        .filter(TelegramConnection.id == connection_id)
        .first()
    )
    if not connection:
        raise HTTPException(status_code=404, detail="Connection not found")
    if not connection.is_active:
        raise HTTPException(status_code=400, detail="Connection is inactive")

    context = MessagingContext(
        connection_id=connection_id,
        name=name,
        mode=ContextMode(mode),
        chat_id=chat_id,
    )
    db.add(context)
    db.commit()
    return RedirectResponse(url="/admin", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/admin/connections/{connection_id}/deactivate")
def deactivate_connection_from_ui(
    connection_id: int,
    _: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    connection = (
        db.query(TelegramConnection)
        .filter(TelegramConnection.id == connection_id)
        .first()
    )
    if connection:
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
        db.commit()
    return RedirectResponse(url="/admin", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/admin/secrets")
def create_managed_secret_from_ui(
    name: str = Form(),
    value: str = Form(),
    secret_type: str = Form(default="generic"),
    description: str = Form(default=""),
    _: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    create_or_update_managed_secret(
        db,
        name=name,
        value=value,
        secret_type=secret_type,
        description=description or None,
    )
    db.commit()
    return RedirectResponse(url="/admin", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/admin/secrets/{name}/deactivate")
def deactivate_managed_secret_from_ui(
    name: str,
    _: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    deactivate_managed_secret(db, name=name)
    db.commit()
    return RedirectResponse(url="/admin", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/admin/onboarding/create", response_class=HTMLResponse)
async def create_onboarding_from_ui(
    request: Request,
    connection_id: int = Form(),
    target_label: str = Form(default=""),
    ttl_seconds: int = Form(default=900),
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    connection = (
        db.query(TelegramConnection)
        .filter(TelegramConnection.id == connection_id)
        .first()
    )
    if not connection:
        return _render_onboarding(
            request=request,
            admin=admin,
            db=db,
            error="Connection not found",
        )
    if connection.type != ConnectionType.bot:
        return _render_onboarding(
            request=request,
            admin=admin,
            db=db,
            error="Onboarding requires a bot connection",
        )
    if not connection.secret_ref_token:
        return _render_onboarding(
            request=request,
            admin=admin,
            db=db,
            error="Selected bot has no token secret reference",
        )

    try:
        token_value = resolve_secret(connection.secret_ref_token, db)
        me = await get_me(token_value)
        username = (me.get("result") or {}).get("username")
        if not username:
            return _render_onboarding(
                request=request,
                admin=admin,
                db=db,
                error="Cannot determine bot username via Telegram getMe",
            )
        connection.bot_username = username
        db.add(connection)

        link = OnboardingLink(
            token=secrets.token_urlsafe(18),
            connection_id=connection.id,
            target_label=(target_label or "").strip() or None,
            status="pending",
            expires_at=(datetime.now(UTC) + timedelta(seconds=ttl_seconds)).replace(
                tzinfo=None
            ),
        )
        db.add(link)
        db.commit()
    except Exception as exc:
        db.rollback()
        return _render_onboarding(
            request=request,
            admin=admin,
            db=db,
            error=f"Create onboarding link failed: {exc}",
        )

    return _render_onboarding(
        request=request,
        admin=admin,
        db=db,
        result="Onboarding link created",
    )


@router.post("/admin/onboarding/process", response_class=HTMLResponse)
async def process_onboarding_from_ui(
    request: Request,
    connection_id: int = Form(),
    limit: int = Form(default=50),
    offset: str = Form(default=""),
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    connection = (
        db.query(TelegramConnection)
        .filter(TelegramConnection.id == connection_id)
        .first()
    )
    if not connection or connection.type != ConnectionType.bot:
        return _render_onboarding(
            request=request,
            admin=admin,
            db=db,
            error="Select a valid bot connection",
        )
    if not connection.secret_ref_token:
        return _render_onboarding(
            request=request,
            admin=admin,
            db=db,
            error="Selected bot has no token secret reference",
        )

    processed = 0
    completed = 0
    start_without_token = 0
    max_update_id: int | None = None
    try:
        token_value = resolve_secret(connection.secret_ref_token, db)
        parsed_offset = int(offset.strip()) if offset.strip() else None
        updates = await get_updates(
            token=token_value, offset=parsed_offset, limit=limit
        )
        items = updates.get("result") if isinstance(updates, dict) else []
        processed = len(items or [])
        for item in items or []:
            update_id = item.get("update_id")
            if isinstance(update_id, int):
                max_update_id = (
                    update_id
                    if max_update_id is None
                    else max(max_update_id, update_id)
                )

            message = item.get("message") or item.get("edited_message") or {}
            text = str(message.get("text") or "")
            if is_start_command_without_token(text):
                start_without_token += 1

            link = process_telegram_update_for_onboarding(db, connection, item)
            if link:
                completed += 1

        if max_update_id is not None:
            await get_updates(token=token_value, offset=max_update_id + 1, limit=1)

        db.commit()
    except Exception as exc:
        db.rollback()
        return _render_onboarding(
            request=request,
            admin=admin,
            db=db,
            error=f"Process onboarding failed: {exc}",
        )

    return _render_onboarding(
        request=request,
        admin=admin,
        db=db,
        result=(
            f"Processed {processed} updates, completed {completed} onboarding link(s), "
            f"/start without token: {start_without_token}"
        ),
    )


@router.post("/admin/onboarding/{link_id}/delete", response_class=HTMLResponse)
def delete_onboarding_link_from_ui(
    request: Request,
    link_id: int,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    link = db.query(OnboardingLink).filter(OnboardingLink.id == link_id).first()
    if not link:
        return _render_onboarding(
            request=request,
            admin=admin,
            db=db,
            error="Onboarding link not found",
        )
    db.delete(link)
    db.commit()
    return _render_onboarding(
        request=request,
        admin=admin,
        db=db,
        result=f"Deleted onboarding link {link_id}",
    )


async def _forward_runtime(
    request: Request,
    path: str,
    method: str,
    dex_token: str,
    payload: dict | None = None,
) -> tuple[str, str]:
    base_url = f"{request.url.scheme}://{request.headers.get('host')}"
    headers = {"Authorization": f"Bearer {dex_token.strip()}"}
    try:
        async with httpx.AsyncClient(timeout=25.0) as client:
            if method == "POST":
                response = await client.post(
                    f"{base_url}{path}",
                    headers={**headers, "Content-Type": "application/json"},
                    json=payload or {},
                )
            else:
                response = await client.get(
                    f"{base_url}{path}", headers=headers, params=payload or {}
                )
    except Exception as exc:
        return "", f"Runtime call failed: {exc}"

    if response.headers.get("content-type", "").startswith("application/json"):
        return response.text, "" if response.status_code < 400 else response.text
    if response.status_code >= 400:
        return "", response.text
    return response.text, ""


@router.post("/admin/runtime/send", response_class=HTMLResponse)
async def runtime_send_from_ui(
    request: Request,
    context_id: int = Form(),
    text: str = Form(),
    dex_token: str = Form(),
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    result, error = await _forward_runtime(
        request,
        path=f"/gateway/contexts/{context_id}/send",
        method="POST",
        dex_token=dex_token,
        payload={"text": text},
    )
    return _render_dashboard(
        request=request,
        admin=admin,
        db=db,
        runtime_result=result,
        runtime_error=error,
    )


@router.post("/admin/runtime/updates", response_class=HTMLResponse)
async def runtime_updates_from_ui(
    request: Request,
    context_id: int = Form(),
    offset: str = Form(default=""),
    dex_token: str = Form(),
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    query: dict[str, str] = {}
    if offset.strip():
        query["offset"] = offset.strip()
    result, error = await _forward_runtime(
        request,
        path=f"/gateway/contexts/{context_id}/updates",
        method="GET",
        dex_token=dex_token,
        payload=query,
    )
    return _render_dashboard(
        request=request,
        admin=admin,
        db=db,
        runtime_result=result,
        runtime_error=error,
    )


@router.post("/admin/runtime/otp/issue", response_class=HTMLResponse)
async def runtime_otp_issue_from_ui(
    request: Request,
    context_id: int = Form(),
    purpose: str = Form(default="auth"),
    ttl_seconds: int = Form(default=300),
    length: int = Form(default=6),
    target_label: str = Form(default=""),
    dex_token: str = Form(),
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    result, error = await _forward_runtime(
        request,
        path="/gateway/otp/issue",
        method="POST",
        dex_token=dex_token,
        payload={
            "context_id": context_id,
            "purpose": purpose,
            "ttl_seconds": ttl_seconds,
            "length": length,
            "target_label": target_label or None,
        },
    )
    return _render_dashboard(
        request=request,
        admin=admin,
        db=db,
        runtime_result=result,
        runtime_error=error,
    )


@router.post("/admin/runtime/otp/verify", response_class=HTMLResponse)
async def runtime_otp_verify_from_ui(
    request: Request,
    challenge_id: str = Form(),
    code: str = Form(),
    dex_token: str = Form(),
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    result, error = await _forward_runtime(
        request,
        path="/gateway/otp/verify",
        method="POST",
        dex_token=dex_token,
        payload={"challenge_id": challenge_id, "code": code},
    )
    return _render_dashboard(
        request=request,
        admin=admin,
        db=db,
        runtime_result=result,
        runtime_error=error,
    )
