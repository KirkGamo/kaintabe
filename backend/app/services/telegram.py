"""Outgoing Telegram messages (works in both polling and webhook mode)."""
import logging

import httpx

from app.config import settings

log = logging.getLogger(__name__)


async def send_message(chat_id: int | None, text: str) -> bool:
    """Best effort: a failed notification must never break the claim/confirm flow."""
    if not chat_id or not settings.telegram_bot_token:
        return False
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            res = await client.post(
                f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage",
                json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"},
            )
        if res.status_code != 200:
            log.warning("telegram sendMessage failed: %s %s", res.status_code, res.text[:200])
            return False
        return True
    except httpx.HTTPError as e:
        log.warning("telegram sendMessage error: %s", type(e).__name__)
        return False


async def send_photo(chat_id: int | None, photo_url: str, caption: str) -> bool:
    """Best effort, like send_message."""
    if not chat_id or not settings.telegram_bot_token:
        return False
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            res = await client.post(
                f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendPhoto",
                json={"chat_id": chat_id, "photo": photo_url, "caption": caption, "parse_mode": "Markdown"},
            )
        if res.status_code != 200:
            log.warning("telegram sendPhoto failed: %s %s", res.status_code, res.text[:200])
            return False
        return True
    except httpx.HTTPError as e:
        log.warning("telegram sendPhoto error: %s", type(e).__name__)
        return False
