"""R1: conversations and drafts survive a bot restart (DbPersistence against the real DB)."""
import asyncio
import itertools
import json
from unittest.mock import AsyncMock, patch

import pytest
from telegram import Update

from app import db
from app.bot import handlers as h
from app.bot.persistence import DbPersistence
from tests.test_routing import FakeTelegram

BOT_ID = "persist-test"  # never a real bot id
CHAT = -660001
_ids = itertools.count(1)


def cleanup():
    with db.connect() as conn:
        conn.execute("delete from bot_state where bot_id in (%s, %s)", (BOT_ID, BOT_ID + "-other"))
        conn.execute("delete from donations where donor_id in (select id from donors where telegram_chat_id = %s)", (CHAT,))
        conn.execute("delete from donors where telegram_chat_id = %s", (CHAT,))


@pytest.fixture(autouse=True)
def clean():
    cleanup()
    yield
    cleanup()


def run(coro):
    return asyncio.run(coro)


# --- DbPersistence unit tests -----------------------------------------------------------

def test_user_data_round_trip_is_json_safe():
    import uuid
    from datetime import datetime, timezone

    p = DbPersistence(BOT_ID)
    data = {"draft": {"photo_file_id": "abc", "est_kg": 2.0, "safety_checklist": {"hygienic": True}},
            "donor": {"id": uuid.uuid4(), "created_at": datetime.now(timezone.utc), "lat": 10.7}}
    run(p.update_user_data(CHAT, data))
    loaded = run(p.get_user_data())[CHAT]
    assert loaded["draft"] == data["draft"]
    assert loaded["donor"]["id"] == str(data["donor"]["id"])  # UUIDs come back as strings
    assert loaded["donor"]["lat"] == 10.7

    run(p.update_user_data(CHAT, {}))  # nothing in progress -> row removed
    assert CHAT not in run(p.get_user_data())


def test_conversation_round_trip_and_delete():
    p = DbPersistence(BOT_ID)
    run(p.update_conversation("posting", (CHAT, CHAT), h.QUANTITY))
    assert run(p.get_conversations("posting")) == {(CHAT, CHAT): h.QUANTITY}
    assert run(p.get_conversations("onboarding")) == {}
    run(p.update_conversation("posting", (CHAT, CHAT), None))  # conversation ended
    assert run(p.get_conversations("posting")) == {}


def test_bots_are_isolated():
    run(DbPersistence(BOT_ID).update_conversation("posting", (CHAT, CHAT), h.FOOD))
    assert run(DbPersistence(BOT_ID + "-other").get_conversations("posting")) == {}


# --- restart in the middle of a post ----------------------------------------------------

def msg(text=None, location=None, photo=False, caption=None):
    m = {"message_id": next(_ids), "date": 0, "chat": {"id": CHAT, "type": "private"},
         "from": {"id": CHAT, "is_bot": False, "first_name": "Persist"}}
    if text is not None:
        m["text"] = text
        if text.startswith("/"):
            m["entities"] = [{"type": "bot_command", "offset": 0, "length": len(text)}]
    if location:
        m["location"] = {"latitude": location[0], "longitude": location[1]}
    if photo:
        m["photo"] = [{"file_id": "f1", "file_unique_id": "u1", "width": 100, "height": 100}]
    if caption:
        m["caption"] = caption
    return {"update_id": next(_ids), "message": m}


def tap(data):
    return {"update_id": next(_ids), "callback_query": {
        "id": str(next(_ids)), "from": {"id": CHAT, "is_bot": False, "first_name": "Persist"},
        "chat_instance": "x", "data": data,
        "message": {"message_id": 1, "date": 0, "chat": {"id": CHAT, "type": "private"}, "text": "question?"}}}


async def run_bot_session(updates):
    """One bot process lifetime: start, handle updates, save state, stop (like a deploy)."""
    fake = FakeTelegram()
    app = h.build_application("123:TEST", request=fake, persistence=DbPersistence(BOT_ID))
    await app.initialize()
    for u in updates:
        await app.process_update(Update.de_json(u, app.bot))
    await app.update_persistence()  # what Application.stop() does on SIGTERM
    await app.shutdown()
    return fake


def texts(fake):
    return [p.get("text", "") for e, p in fake.sent if e == "sendMessage"]


def listings():
    with db.connect() as conn:
        return conn.execute(
            "select d.* from donations d join donors o on o.id = d.donor_id where o.telegram_chat_id = %s", (CHAT,)
        ).fetchall()


ONBOARD_BUSINESS = [msg("/start"), tap("role:donor"), msg("Persist Bakery"), tap("type:business"),
                    msg(location=(10.7141, 122.5519)), tap("pledge:yes")]


@pytest.fixture
def no_side_effects():
    with patch.object(h.storage, "upload_photo", new_callable=AsyncMock, return_value="https://example.com/p.jpg"), \
         patch.object(h.ai_intake, "enabled", return_value=False):
        yield


def test_post_survives_restart_mid_questions(no_side_effects):
    run(run_bot_session(ONBOARD_BUSINESS))
    # Session 1: photo + food name, then the bot restarts
    run(run_bot_session([msg(photo=True), msg("Pandesal")]))
    # Session 2 (fresh process): answers continue exactly where they left off
    fake = run(run_bot_session([msg("30 pieces"), tap("kg:1"), tap("hrs:4"), tap("lt:donation"), tap("loc:saved"),
                                tap("safe:0:yes"), tap("safe:1:yes"), tap("safe:2:yes")]))
    assert not any("expired" in t for t in texts(fake))
    assert any("Live now" in t for t in texts(fake))
    rows = listings()
    assert len(rows) == 1
    assert (rows[0]["food_type"], rows[0]["quantity"], rows[0]["listing_type"]) == ("Pandesal", "30 pieces", "donation")


def test_sale_survives_restart_after_price(no_side_effects):
    run(run_bot_session(ONBOARD_BUSINESS))
    run(run_bot_session([msg(photo=True, caption="Ensaymada"), msg("12 pcs"), tap("kg:0"), tap("hrs:8"),
                         tap("lt:sale"), msg("120")]))
    fake = run(run_bot_session([tap("loc:saved"), tap("safe:0:yes"), tap("safe:1:yes"), tap("safe:2:yes")]))
    assert any("For sale at ₱120" in t for t in texts(fake))
    rows = listings()
    assert len(rows) == 1 and rows[0]["listing_type"] == "sale" and float(rows[0]["original_price"]) == 120


def test_state_is_cleared_after_publishing(no_side_effects):
    run(run_bot_session(ONBOARD_BUSINESS))
    run(run_bot_session([msg(photo=True, caption="Turon"), msg("5 pcs"), tap("kg:0"), tap("hrs:2"),
                         tap("lt:donation"), tap("loc:saved"), tap("safe:0:yes"), tap("safe:1:yes"), tap("safe:2:yes")]))
    with db.connect() as conn:
        rows = conn.execute("select kind, data from bot_state where bot_id = %s", (BOT_ID,)).fetchall()
    # no conversation left mid-way and no leftover draft for this user
    assert not [r for r in rows if r["kind"].startswith("conv:")], rows
    user_rows = [json.dumps(r["data"]) for r in rows if r["kind"] == "user"]
    assert not any("draft" in u for u in user_rows)
