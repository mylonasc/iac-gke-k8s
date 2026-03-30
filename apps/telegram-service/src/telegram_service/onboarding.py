from datetime import UTC, datetime

from sqlalchemy.orm import Session

from telegram_service.models import (
    ContextMode,
    MessagingContext,
    OnboardingLink,
    TelegramConnection,
)


def extract_start_token(text: str) -> str | None:
    value = (text or "").strip()
    if not value.startswith("/start"):
        return None
    parts = value.split()
    if len(parts) < 2:
        return None
    return parts[1].strip()


def is_start_command_without_token(text: str) -> bool:
    value = (text or "").strip()
    if not value:
        return False
    parts = value.split()
    if not parts:
        return False
    first = parts[0].lower()
    if not (first == "/start" or first.startswith("/start@")):
        return False
    return len(parts) == 1


def _build_context_name(link: OnboardingLink, chat_id: str) -> str:
    suffix = link.token[:8]
    base = (link.target_label or "user").strip().replace(" ", "-")
    base = "".join(ch for ch in base if ch.isalnum() or ch in ("-", "_"))
    if not base:
        base = f"chat-{chat_id}"
    return f"{base}-{suffix}"[:120]


def complete_onboarding(
    db: Session,
    connection: TelegramConnection,
    token: str,
    chat_id: str,
    telegram_user_id: str | None,
    telegram_username: str | None,
) -> OnboardingLink | None:
    link = (
        db.query(OnboardingLink)
        .filter(
            OnboardingLink.token == token,
            OnboardingLink.connection_id == connection.id,
            OnboardingLink.status == "pending",
        )
        .first()
    )
    if not link:
        return None

    now = datetime.now(UTC).replace(tzinfo=None)
    if link.expires_at <= now:
        link.status = "expired"
        db.add(link)
        db.flush()
        return None

    existing_context = (
        db.query(MessagingContext)
        .filter(
            MessagingContext.connection_id == connection.id,
            MessagingContext.chat_id == chat_id,
            MessagingContext.is_active == True,
        )
        .first()
    )  # noqa: E712

    if existing_context:
        context = existing_context
    else:
        context = MessagingContext(
            connection_id=connection.id,
            name=_build_context_name(link, chat_id),
            mode=ContextMode.send_receive,
            chat_id=chat_id,
            is_active=True,
        )
        db.add(context)
        db.flush()

    link.status = "completed"
    link.chat_id = chat_id
    link.telegram_user_id = telegram_user_id
    link.telegram_username = telegram_username
    link.context_id = context.id
    link.completed_at = now
    db.add(link)
    db.flush()
    return link


def process_telegram_update_for_onboarding(
    db: Session, connection: TelegramConnection, update: dict
) -> OnboardingLink | None:
    message = update.get("message") or update.get("edited_message") or {}
    text = str(message.get("text") or "")
    token = extract_start_token(text)
    if not token:
        return None

    chat = message.get("chat") or {}
    sender = message.get("from") or {}
    chat_id = str(chat.get("id") or "").strip()
    if not chat_id:
        return None

    return complete_onboarding(
        db=db,
        connection=connection,
        token=token,
        chat_id=chat_id,
        telegram_user_id=str(sender.get("id") or "") or None,
        telegram_username=sender.get("username"),
    )
