"""Telegram Mini App identity: verify the `initData` Telegram signs with our bot token.

Spec (core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app):
  data_check_string = sorted "key=value" lines of every field except `hash`, joined by "\\n"
  secret_key        = HMAC_SHA256(key="WebAppData", msg=bot_token)
  valid             = hex(HMAC_SHA256(key=secret_key, msg=data_check_string)) == hash
A valid signature proves the data came from Telegram for OUR bot; `auth_date` bounds its age.
"""
import hashlib
import hmac
import json
import time
from urllib.parse import parse_qsl

import httpx
from fastapi import Header, HTTPException

from app.config import settings

MAX_AGE_S = 24 * 3600


class InvalidInitData(Exception):
    pass


def verify_init_data(init_data: str, bot_token: str, max_age_s: int = MAX_AGE_S, now: float | None = None) -> dict:
    """Return the Telegram user dict ({"id": ..., "first_name": ...}) or raise InvalidInitData."""
    if not init_data or not bot_token:
        raise InvalidInitData("missing")
    fields = dict(parse_qsl(init_data, keep_blank_values=True))
    received = fields.pop("hash", "")
    check_string = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    expected = hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, received):
        raise InvalidInitData("bad signature")
    try:
        auth_date = int(fields.get("auth_date", "0"))
        user = json.loads(fields["user"])
        int(user["id"])
    except (KeyError, ValueError, TypeError) as e:
        raise InvalidInitData("malformed") from e
    if (now or time.time()) - auth_date > max_age_s:
        raise InvalidInitData("expired")
    return user


def sign_init_data(user: dict, bot_token: str, auth_date: int | None = None) -> str:
    """Build initData exactly like Telegram does (used by tests and local tooling)."""
    from urllib.parse import urlencode

    fields = {"auth_date": str(auth_date or int(time.time())), "query_id": "test",
              "user": json.dumps(user, separators=(",", ":"))}
    check_string = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    fields["hash"] = hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()
    return urlencode(fields)


_bot_username: str | None = None


async def bot_username() -> str:
    """This backend's bot username (orgs/individuals are linked per bot). Cached after the first getMe."""
    global _bot_username
    if _bot_username is None:
        async with httpx.AsyncClient(timeout=15) as client:
            res = await client.get(f"https://api.telegram.org/bot{settings.telegram_bot_token}/getMe")
        _bot_username = res.json()["result"]["username"]
    return _bot_username


def telegram_user(x_telegram_init_data: str | None = Header(default=None)) -> dict:
    """FastAPI dependency: the verified Telegram user, or 401."""
    try:
        return verify_init_data(x_telegram_init_data or "", settings.telegram_bot_token)
    except InvalidInitData as e:
        raise HTTPException(401, f"Open the map from the KainTabe Telegram bot to do this ({e}).") from e
