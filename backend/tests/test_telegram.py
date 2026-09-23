"""Outgoing Telegram helpers with the HTTP layer mocked."""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from app.services import telegram


def fake_client(*responses):
    """An httpx.AsyncClient stand-in whose post() returns/raises the given items in order."""
    client = MagicMock()
    client.post = AsyncMock(side_effect=list(responses))
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=client)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return ctx, client


def test_send_photo_uploads_bytes():
    ctx, client = fake_client(httpx.Response(200, json={"ok": True}))
    with patch.object(telegram.httpx, "AsyncClient", return_value=ctx):
        assert asyncio.run(telegram.send_photo(123, b"\xff\xd8jpeg", "thanks"))
    kwargs = client.post.await_args.kwargs
    assert kwargs["files"]["photo"][1] == b"\xff\xd8jpeg"
    assert kwargs["data"]["caption"] == "thanks"


def test_send_photo_falls_back_to_text():
    ctx, _ = fake_client(httpx.Response(400, json={"ok": False, "description": "bad photo"}))
    with patch.object(telegram.httpx, "AsyncClient", return_value=ctx), \
         patch.object(telegram, "send_message", new_callable=AsyncMock, return_value=True) as text:
        assert asyncio.run(telegram.send_photo(123, b"x", "thanks"))
    text.assert_awaited_once_with(123, "thanks")


def test_send_photo_network_error_falls_back_to_text():
    ctx, _ = fake_client(httpx.ConnectError("down"))
    with patch.object(telegram.httpx, "AsyncClient", return_value=ctx), \
         patch.object(telegram, "send_message", new_callable=AsyncMock, return_value=False) as text:
        assert asyncio.run(telegram.send_photo(123, b"x", "thanks")) is False  # never raises
    text.assert_awaited_once()


def test_no_chat_id_is_a_no_op():
    assert asyncio.run(telegram.send_photo(None, b"x", "thanks")) is False
    assert asyncio.run(telegram.send_message(None, "hi")) is False
