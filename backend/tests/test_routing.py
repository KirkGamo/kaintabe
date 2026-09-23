"""Replay real Telegram updates through the full Application (ConversationHandler routing included).

Unit tests in test_bot.py call handlers directly; these catch wiring bugs between them.
Telegram's HTTP API is faked; the database is real.
"""
import asyncio
import itertools
import json

import pytest
from telegram import Update
from telegram.request import BaseRequest

from app import db
from app.bot import handlers as h

CHAT_ID = -990002  # fake chat reserved for routing tests
USER = {"id": CHAT_ID, "is_bot": False, "first_name": "Tester"}
CHAT = {"id": CHAT_ID, "type": "private"}


class FakeTelegram(BaseRequest):
    """Answers every Bot API call with a plausible success and records what the bot sent."""

    def __init__(self):
        self.sent: list[tuple[str, dict]] = []
        self._ids = itertools.count(1000)

    async def initialize(self):
        pass

    async def shutdown(self):
        pass

    async def do_request(self, url, method, request_data=None, **kwargs):
        if "/file/bot" in url:  # downloading a file the user sent
            return 200, b"\xff\xd8fake-photo"
        endpoint = url.rsplit("/", 1)[-1]
        params = request_data.parameters if request_data else {}
        self.sent.append((endpoint, params))
        if endpoint == "getFile":
            result = {"file_id": "f1", "file_unique_id": "u1", "file_path": "photos/f1.jpg"}
        elif endpoint == "getMe":
            result = {"id": 1, "is_bot": True, "first_name": "Dev", "username": "test_bot"}
        elif endpoint in ("sendMessage", "editMessageText"):
            result = {"message_id": next(self._ids), "date": 0, "chat": CHAT, "text": params.get("text", "")}
        else:
            result = True
        return 200, json.dumps({"ok": True, "result": result}).encode()

    def texts(self):
        return [p.get("text", "") for e, p in self.sent if e == "sendMessage"]


_update_ids = itertools.count(1)


def message(text=None, location=None):
    msg = {"message_id": next(_update_ids), "date": 0, "chat": CHAT, "from": USER}
    if text is not None:
        msg["text"] = text
        if text.startswith("/"):
            msg["entities"] = [{"type": "bot_command", "offset": 0, "length": len(text.split()[0])}]
    if location:
        msg["location"] = {"latitude": location[0], "longitude": location[1]}
    return {"update_id": next(_update_ids), "message": msg}


def tap(data):
    return {
        "update_id": next(_update_ids),
        "callback_query": {
            "id": str(next(_update_ids)), "from": USER, "chat_instance": "x", "data": data,
            "message": {"message_id": 1, "date": 0, "chat": CHAT, "text": "question?"},
        },
    }


def donor():
    with db.connect() as conn:
        return conn.execute("select name, type from donors where telegram_chat_id = %s", (CHAT_ID,)).fetchone()


@pytest.fixture(autouse=True)
def clean():
    def wipe():
        with db.connect() as conn:
            conn.execute("delete from donors where telegram_chat_id = %s", (CHAT_ID,))
    wipe()
    yield
    wipe()


def run_updates(updates):
    """Feed updates through a real Application, in order. Returns the fake Telegram API."""
    async def go():
        fake = FakeTelegram()
        app = h.build_application("123:TEST", request=fake)
        await app.initialize()
        for u in updates:
            await app.process_update(Update.de_json(u, app.bot))
        await app.shutdown()
        return fake
    return asyncio.run(go())


ONBOARD = [message("/start"), tap("role:donor"), message("Routing Bakery"), tap("type:business"),
           message(location=(10.7141, 122.5519)), tap("pledge:yes")]


def test_start_onboards_through_real_routing():
    fake = run_updates(ONBOARD)
    assert donor() == {"name": "Routing Bakery", "type": "business"}
    assert any("all set" in t for t in fake.texts())


def test_profile_changes_type_keeping_name_and_spot():
    run_updates(ONBOARD)
    fake = run_updates([message("/profile"), tap("keep:name"), tap("type:household"), tap("keep:loc")])
    assert donor() == {"name": "Routing Bakery", "type": "household"}, fake.texts()
    assert any("Update your profile" in t for t in fake.texts())
    assert any("Profile updated" in t for t in fake.texts())
    assert not any("pledge" in t.lower() for t in fake.texts())  # already pledged: not asked again
    with db.connect() as conn:
        spot = conn.execute("select lat, lng from donors where telegram_chat_id = %s", (CHAT_ID,)).fetchone()
    assert (spot["lat"], spot["lng"]) == (10.7141, 122.5519)


def test_profile_new_name_and_spot():
    run_updates(ONBOARD)
    run_updates([message("/profile"), message("Lugawan ni Sis"), tap("type:business"),
                 message(location=(10.7290, 122.5580))])
    assert donor() == {"name": "Lugawan ni Sis", "type": "business"}


def test_profile_before_onboarding_starts_welcome():
    fake = run_updates([message("/profile")])
    assert any("What brings you here" in t for t in fake.texts())
    assert donor() is None


# --- after a restart the in-memory conversation is gone; the bot must still answer ---

def test_button_from_before_restart_gets_expired_notice():
    run_updates(ONBOARD)
    fake = run_updates([tap("hrs:2")])  # fresh Application = restarted bot
    assert any("expired" in t for t in fake.texts())
    assert any(e == "editMessageReplyMarkup" for e, _ in fake.sent)  # old buttons removed


def test_cancel_works_outside_a_conversation():
    fake = run_updates([message("/cancel")])
    assert any("Cancelled" in t for t in fake.texts())


def test_cancel_mid_post_answers_once():
    run_updates(ONBOARD)
    fake = run_updates([message("/start"), message("/cancel")])
    assert sum("Cancelled" in t for t in fake.texts()) == 1


def test_stray_text_gets_a_hint():
    run_updates(ONBOARD)
    fake = run_updates([message("hello?")])
    assert any("send a photo" in t for t in fake.texts())


def test_onboarding_text_is_not_swallowed_by_catch_all():
    fake = run_updates(ONBOARD)
    assert not any("To share food, just send a photo" in t for t in fake.texts())
    assert donor() is not None
