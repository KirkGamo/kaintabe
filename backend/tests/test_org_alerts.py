"""R3b: new-food alerts for partner orgs - SQL rules (rolled back) and the full Telegram flow."""
import asyncio
import itertools
from unittest.mock import AsyncMock, patch

import pytest
from telegram import Update

from app import db
from app.bot import handlers as h
from app.services import org_alerts, repo
from tests.conftest import insert_donation
from tests.test_routing import FakeTelegram

BOT = "test_bot"
O1, O2 = -330001, -330002
MINE: set = set()  # listings created by these tests (the shared DB also holds real ones)


def org(conn, chat, lat, lng, radius=5000, via=BOT):
    return conn.execute(
        "insert into recipients (name, type, lat, lng, service_radius_m, telegram_chat_id, via_bot, review_status) "
        "values (%s, 'partner_org', %s, %s, %s, %s, %s, 'pending_review') returning id",
        (f"Test Org {abs(chat)}", lat, lng, radius, chat, via),
    ).fetchone()["id"]


def listing(conn, **kw):
    d = insert_donation(conn, lat=10.7250, lng=122.5575, **kw)
    MINE.add(d)
    return d


def alerts(conn, bot=BOT):
    return [a for a in conn.execute("select * from claim_org_alerts(%s)", (bot,)).fetchall() if a["donation_id"] in MINE]


# --- SQL rules ------------------------------------------------------------------------

def test_org_in_range_alerted_once(conn):
    o = org(conn, O1, 10.7300, 122.5600)  # ~600 m away
    d = listing(conn)
    first = alerts(conn)
    assert [(a["donation_id"], a["recipient_id"], a["chat_id"]) for a in first] == [(d, o, O1)]
    assert alerts(conn) == []  # never twice


def test_org_own_service_radius_limits_alerts(conn):
    org(conn, O1, 10.6965, 122.5645, radius=3000)  # City Proper, ~3.2 km away; only travels 3 km
    listing(conn, radius_m=8000)  # listing reaches it, but the org said 3 km
    assert alerts(conn) == []


def test_widening_into_range_alerts_then(conn):
    org(conn, O1, 10.6965, 122.5645, radius=8000)  # ~3.2 km away
    d = listing(conn, radius_m=2000)
    assert alerts(conn) == []
    conn.execute("update donations set search_radius_m = 4000 where id = %s", (d,))
    assert [a["donation_id"] for a in alerts(conn)] == [d]


@pytest.mark.parametrize("status", ["claimed", "withdrawn", "completed", "expired"])
def test_only_claimable_listings(conn, status):
    org(conn, O1, 10.7300, 122.5600)
    listing(conn, status=status)
    assert alerts(conn) == []


def test_other_bots_orgs_not_alerted_by_this_bot(conn):
    org(conn, O1, 10.7300, 122.5600, via="other_bot")
    listing(conn)
    assert alerts(conn) == []
    assert len(alerts(conn, bot="other_bot")) == 1


def test_sale_alert_carries_price(conn):
    org(conn, O1, 10.7300, 122.5600)
    listing(conn, listing_type="sale", original_price=100, current_price=80)
    a = alerts(conn)[0]
    assert "For sale: about ₱80" in org_alerts.alert_text(a)
    assert org_alerts.alert_keyboard(a).inline_keyboard[0][0].text.startswith("🛒 Reserve")


# --- full flow through the bot ------------------------------------------------------------

_ids = itertools.count(1)


def tap(chat, data):
    return {"update_id": next(_ids), "callback_query": {
        "id": str(next(_ids)), "from": {"id": chat, "is_bot": False, "first_name": "Org"},
        "chat_instance": "x", "data": data,
        "message": {"message_id": 1, "date": 0, "chat": {"id": chat, "type": "private"}, "text": "🍱 New food near you"}}}


def photo(chat):
    return {"update_id": next(_ids), "message": {
        "message_id": next(_ids), "date": 0, "chat": {"id": chat, "type": "private"},
        "from": {"id": chat, "is_bot": False, "first_name": "Org"},
        "photo": [{"file_id": "f1", "file_unique_id": "u1", "width": 100, "height": 100}]}}


@pytest.fixture
def two_orgs_and_a_listing():
    with db.connect() as conn:
        o1 = org(conn, O1, 10.7300, 122.5600)
        o2 = org(conn, O2, 10.7200, 122.5550)
        d = insert_donation(conn, lat=10.7250, lng=122.5575, food_type="Alert test pancit", est_kg=3)
    yield o1, o2, d
    with db.connect() as conn:
        conn.execute("delete from claims where donation_id = %s", (d,))
        conn.execute("delete from donations where id = %s", (d,))
        conn.execute("delete from recipients where telegram_chat_id in (%s, %s)", (O1, O2))


def test_alert_claim_race_and_photo_confirm(two_orgs_and_a_listing):
    o1, o2, d = two_orgs_and_a_listing

    async def go():
        fake = FakeTelegram()
        app = h.build_application("123:TEST", request=fake)
        await app.initialize()
        with patch.object(h.storage, "upload_photo", new_callable=AsyncMock, return_value="https://example.com/p.jpg"), \
             patch.object(h.tg_out, "send_message", new_callable=AsyncMock) as donor_msg, \
             patch.object(h.tg_out, "send_photo", new_callable=AsyncMock) as donor_photo:
            await org_alerts.send_pending(app.bot)
            alerted = {str(p["chat_id"]) for e, p in fake.sent
                       if e == "sendMessage" and "Alert test pancit" in p.get("text", "")}
            assert alerted == {str(O1), str(O2)}

            for u in (tap(O1, f"oclaim:{d}"), tap(O2, f"oclaim:{d}"), photo(O1)):
                await app.process_update(Update.de_json(u, app.bot))
            edits = {str(p["chat_id"]): p["text"] for e, p in fake.sent if e == "editMessageText"}
            assert "Claimed for Test Org 330001" in edits[str(O1)].replace("*", "")
            assert "Someone else got this one first" in edits[str(O2)]
            assert "Claimed" in donor_msg.await_args.args[1]
            assert any("Pickup confirmed" in p.get("text", "") for e, p in fake.sent if e == "sendMessage")
            donor_photo.assert_awaited_once()
        await app.shutdown()

    asyncio.run(go())
    with db.connect() as conn:
        assert conn.execute("select status from donations where id = %s", (d,)).fetchone()["status"] == "completed"
        claim = conn.execute("select recipient_id from claims where donation_id = %s", (d,)).fetchone()
    assert claim["recipient_id"] == o1


def test_non_org_cannot_claim_from_alert(two_orgs_and_a_listing):
    _, _, d = two_orgs_and_a_listing

    async def go():
        fake = FakeTelegram()
        app = h.build_application("123:TEST", request=fake)
        await app.initialize()
        await app.process_update(Update.de_json(tap(-330999, f"oclaim:{d}"), app.bot))
        await app.shutdown()
        return fake

    fake = asyncio.run(go())
    assert any("Only registered partner organizations" in p.get("text", "")
               for e, p in fake.sent if e == "answerCallbackQuery")
    assert repo.claimer_of(str(d)) is None
