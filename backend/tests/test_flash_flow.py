"""Flash offers end to end through the real bot routing: opt in -> offer -> race -> photo confirm -> /stop.

Telegram is faked (FakeTelegram), storage and outgoing donor messages are mocked, the DB is real.
"""
import asyncio
import itertools
from unittest.mock import AsyncMock, patch

import pytest
from telegram import Update

from app import db
from app.bot import handlers as h
from app.services import flash
from tests.conftest import insert_donation
from tests.test_routing import FakeTelegram

A, B = -770001, -770002  # two fake people
NEAR_JARO = (10.7300, 122.5600)
_ids = itertools.count(1)


def user(chat):
    return {"id": chat, "is_bot": False, "first_name": f"Person{abs(chat) % 10}"}


def msg(chat, text=None, location=None, photo=False):
    m = {"message_id": next(_ids), "date": 0, "chat": {"id": chat, "type": "private"}, "from": user(chat)}
    if text is not None:
        m["text"] = text
        if text.startswith("/"):
            m["entities"] = [{"type": "bot_command", "offset": 0, "length": len(text)}]
    if location:
        m["location"] = {"latitude": location[0], "longitude": location[1]}
    if photo:
        m["photo"] = [{"file_id": "f1", "file_unique_id": "u1", "width": 100, "height": 100}]
    return {"update_id": next(_ids), "message": m}


def tap(chat, data):
    return {"update_id": next(_ids), "callback_query": {
        "id": str(next(_ids)), "from": user(chat), "chat_instance": "x", "data": data,
        "message": {"message_id": 1, "date": 0, "chat": {"id": chat, "type": "private"}, "text": "📣 Flash offer"}}}


class Harness:
    """One long-lived bot Application (no restart between steps)."""

    def __init__(self):
        self.fake = FakeTelegram()
        self.app = h.build_application("123:TEST", request=self.fake)

    async def __aenter__(self):
        await self.app.initialize()
        return self

    async def __aexit__(self, *exc):
        await self.app.shutdown()

    async def send(self, *updates):
        for u in updates:
            await self.app.process_update(Update.de_json(u, self.app.bot))

    def texts_to(self, chat):
        return [p.get("text", "") for e, p in self.fake.sent
                if e in ("sendMessage", "editMessageText") and str(p.get("chat_id")) == str(chat)]


def cleanup():
    with db.connect() as conn:
        conn.execute("delete from claims where recipient_id in "
                     "(select id from recipients where telegram_chat_id in (%s, %s))", (A, B))
        conn.execute("delete from donations where food_type = 'Flash test pancit'")
        conn.execute("delete from recipients where telegram_chat_id in (%s, %s)", (A, B))
        conn.execute("delete from donors where telegram_chat_id in (%s, %s)", (A, B))


@pytest.fixture(autouse=True)
def clean():
    cleanup()
    yield
    cleanup()


@pytest.fixture
def mocks():
    with patch.object(h.storage, "upload_photo", new_callable=AsyncMock, return_value="https://example.com/pickup.jpg") as up, \
         patch.object(h.tg_out, "send_message", new_callable=AsyncMock) as donor_msg, \
         patch.object(h.tg_out, "send_photo", new_callable=AsyncMock) as donor_photo:
        yield up, donor_msg, donor_photo


def escalated_listing():
    with db.connect() as conn:
        return insert_donation(conn, food_type="Flash test pancit", quantity="2 trays", est_kg=3,
                               lat=10.7250, lng=122.5575, radius_m=8000, status="escalated")


def opt_in(chat, location=NEAR_JARO, name=None):
    """Join the flash list; `name` is typed, otherwise the Telegram first name is taken with one tap."""
    named = msg(chat, name) if name else tap(chat, "indname:tg")
    return [msg(chat, "/start"), tap(chat, "role:recipient"), named, msg(chat, location=location)]


def test_full_flash_flow(mocks):
    upload, donor_msg, donor_photo = mocks

    async def go():
        async with Harness() as bot:
            await bot.send(*opt_in(A, name="Ana Typed"), *opt_in(B))
            assert any("on the list" in t for t in bot.texts_to(A))

            d = escalated_listing()
            assert await flash.send_pending(bot.app.bot) >= 2  # A and B (plus any real people nearby)
            offers = [p for e, p in bot.fake.sent if e == "sendMessage" and "Flash offer near you" in p.get("text", "")]
            assert {str(p["chat_id"]) for p in offers} >= {str(A), str(B)}
            assert await flash.send_pending(bot.app.bot) == 0  # never twice

            # A taps first and wins; B is too late
            await bot.send(tap(A, f"flash:{d}"), tap(B, f"flash:{d}"))
            assert any("It's yours" in t for t in bot.texts_to(A))
            assert any("got this one first" in t for t in bot.texts_to(B))
            donor_msg.assert_awaited_once()
            assert "Claimed" in donor_msg.await_args.args[1]
            assert "Ana Typed" in donor_msg.await_args.args[1]  # the name A chose, not the Telegram one

            # A sends the pickup photo -> confirmed, donor thanked, counts as completed
            await bot.send(msg(A, photo=True))
            assert any("Pickup confirmed" in t for t in bot.texts_to(A))
            upload.assert_awaited_once_with("pickup-photos", b"\xff\xd8fake-photo")
            donor_photo.assert_awaited_once()
            with db.connect() as conn:
                assert conn.execute("select status from donations where id = %s", (d,)).fetchone()["status"] == "completed"

    asyncio.run(go())


def test_stop_ends_offers(mocks):
    async def go():
        async with Harness() as bot:
            await bot.send(*opt_in(A), msg(A, "/stop"))
            assert any("won't get flash offers" in t for t in bot.texts_to(A))
            escalated_listing()
            await flash.send_pending(bot.app.bot)
            assert not any("Flash offer near you" in t for t in bot.texts_to(A))
            await bot.send(msg(A, "/stop"))
            assert any("not on the flash-offer list" in t for t in bot.texts_to(A))

    asyncio.run(go())


def test_non_member_tap_is_refused(mocks):
    async def go():
        async with Harness() as bot:
            d = escalated_listing()
            await bot.send(tap(A, f"flash:{d}"))
            answers = [p for e, p in bot.fake.sent if e == "answerCallbackQuery"]
            assert answers and "people on the list" in answers[-1].get("text", "")
            with db.connect() as conn:
                assert conn.execute("select status from donations where id = %s", (d,)).fetchone()["status"] == "escalated"

    asyncio.run(go())


def test_donor_can_join_flash_list_and_confirm_by_photo(mocks):
    async def go():
        async with Harness() as bot:
            await bot.send(msg(A, "/start"), tap(A, "role:donor"), msg(A, "Flash Donor"), tap(A, "type:household"),
                           msg(A, location=NEAR_JARO), tap(A, "pledge:yes"))  # A is a donor...
            await bot.send(*opt_in(A))  # ...and joins the flash list via the Welcome-back button
            assert any("on the list" in t for t in bot.texts_to(A))

            d = escalated_listing()
            await flash.send_pending(bot.app.bot)
            await bot.send(tap(A, f"flash:{d}"), msg(A, photo=True))
            assert any(t == "Is this photo…" for t in bot.texts_to(A))  # pickup or new food?
            await bot.send(tap(A, "purpose:pickup"))
            assert any("Pickup confirmed" in t for t in bot.texts_to(A))

            await bot.send(msg(A, "/start"))
            assert any("also on the flash-offer list" in t for t in bot.texts_to(A))

    asyncio.run(go())
