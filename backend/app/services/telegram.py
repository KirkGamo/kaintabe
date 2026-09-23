"""Outgoing Telegram messages (works in both polling and webhook mode)."""
import json
import logging

import httpx

from app.config import settings

log = logging.getLogger(__name__)


def map_markup() -> dict | None:
    """An 'Open map' button (Telegram Mini App) for donor notifications, if an https web URL is set."""
    url = settings.map_url
    return {"inline_keyboard": [[{"text": "🗺️ Open map", "web_app": {"url": url}}]]} if url else None


async def send_message(chat_id: int | None, text: str, with_map: bool = True) -> bool:
    """Best effort: a failed notification must never break the claim/confirm flow."""
    if not chat_id or not settings.telegram_bot_token:
        return False
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
    if with_map and (markup := map_markup()):
        payload["reply_markup"] = markup
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            res = await client.post(
                f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage", json=payload
            )
        if res.status_code != 200:
            log.warning("telegram sendMessage failed: %s %s", res.status_code, res.text[:200])
            return False
        return True
    except httpx.HTTPError as e:
        log.warning("telegram sendMessage error: %s", type(e).__name__)
        return False


async def send_photo(chat_id: int | None, photo: bytes, caption: str) -> bool:
    """Upload the photo bytes directly (Telegram fetching our storage URL is unreliable).

    Best effort: if the photo can't be sent, the caption still goes out as a text message.
    """
    if not chat_id or not settings.telegram_bot_token:
        return False
    data = {"chat_id": str(chat_id), "caption": caption, "parse_mode": "Markdown"}
    if markup := map_markup():
        data["reply_markup"] = json.dumps(markup)  # multipart form: JSON-encoded like the Bot API expects
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            res = await client.post(
                f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendPhoto",
                data=data,
                files={"photo": ("pickup.jpg", photo, "image/jpeg")},
            )
        if res.status_code == 200:
            return True
        log.warning("telegram sendPhoto failed: %s %s", res.status_code, res.text[:200])
    except httpx.HTTPError as e:
        log.warning("telegram sendPhoto error: %s", type(e).__name__)
    return await send_message(chat_id, caption)
