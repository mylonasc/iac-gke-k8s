from typing import Any

import httpx

from telegram_service.config import get_settings

settings = get_settings()


async def send_message(token: str, chat_id: str, text: str) -> dict[str, Any]:
    url = f"{settings.telegram_api_base}/bot{token}/sendMessage"
    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.post(url, json={"chat_id": chat_id, "text": text})
        response.raise_for_status()
        return response.json()


async def get_updates(
    token: str, offset: int | None = None, limit: int = 50
) -> dict[str, Any]:
    url = f"{settings.telegram_api_base}/bot{token}/getUpdates"
    payload: dict[str, Any] = {"limit": limit, "timeout": 1}
    if offset is not None:
        payload["offset"] = offset

    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.post(url, json=payload)
        response.raise_for_status()
        return response.json()


async def get_me(token: str) -> dict[str, Any]:
    url = f"{settings.telegram_api_base}/bot{token}/getMe"
    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.get(url)
        response.raise_for_status()
        return response.json()
