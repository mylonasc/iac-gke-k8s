import os
from typing import Any

from telethon import TelegramClient
from telethon.sessions import StringSession


def build_client(session_string: str | None = None) -> TelegramClient:
    api_id_raw = os.getenv("TELEGRAM_API_ID", "")
    api_hash = os.getenv("TELEGRAM_API_HASH", "")
    if not api_id_raw or not api_hash:
        raise RuntimeError(
            "TELEGRAM_API_ID and TELEGRAM_API_HASH are required for user login flow"
        )

    api_id = int(api_id_raw)
    string_session = StringSession(session_string or "")
    return TelegramClient(string_session, api_id=api_id, api_hash=api_hash)


def _parse_chat_target(chat_id: str) -> int | str:
    raw = chat_id.strip()
    if not raw:
        raise ValueError("chat_id is required")
    if raw.lstrip("-").isdigit():
        return int(raw)
    return raw


async def send_user_message(
    session_string: str, chat_id: str, text: str
) -> dict[str, Any]:
    client = build_client(session_string=session_string)
    await client.connect()
    try:
        target = _parse_chat_target(chat_id)
        message = await client.send_message(entity=target, message=text)
        return {
            "id": message.id,
            "text": message.message,
            "date": message.date.isoformat() if message.date else None,
            "peer_id": str(message.peer_id),
        }
    finally:
        await client.disconnect()


async def get_user_messages(
    session_string: str,
    chat_id: str,
    limit: int = 20,
    min_id: int | None = None,
) -> dict[str, Any]:
    client = build_client(session_string=session_string)
    await client.connect()
    try:
        target = _parse_chat_target(chat_id)
        messages = await client.get_messages(
            entity=target, limit=limit, min_id=min_id or 0
        )
        items = [
            {
                "id": item.id,
                "text": item.message,
                "date": item.date.isoformat() if item.date else None,
                "from_id": str(item.from_id),
            }
            for item in messages
        ]
        return {"count": len(items), "messages": items}
    finally:
        await client.disconnect()
