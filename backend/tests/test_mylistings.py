"""R2 bot: /mylistings and 'Mark as gone' through real routing (fake Telegram, real DB)."""
import asyncio
import itertools

import pytest
from telegram import Update

from app import db
from app.bot import handlers as h
from app.services import repo
from tests.test_routing import FakeTelegram

CHAT = -550001
JARO = "00000000-0000-0000-0000-00000000a001"
_ids = itertools.count(1)


def msg(text=None, location=None):
    m = {"message_id": next(_ids), "date": 0, "chat": {"id": CHAT, "type": "private"},
         "from": {"id": CHAT, "is_bot": False, "first_name": "Lister"}}
    if text is not None:
        m["text"] = text
        if text.startswith("/"):
            m["entities"] = [{"type": "bot_command", "offset": 0, "length": len(text)}]
    if location:
        m["location"] = {"latitude": location[0], "longitude": location[1]}
    return {"update_id": next(_ids), "message": m}


def tap(data):
    return {"update_id": next(_ids), "callback_query": {
        "id": str(next(_ids)), "from": {"id": CHAT, "is_bot": False, "first_name": "Lister"},
        "chat_instance": "x", "data": data,
        "message": {"message_id": 1, "date": 0, "chat": {"id": CHAT, "type": "private"}, "text": "list"}}}


def cleanup():
    with db.connect() as conn:
        conn.execute("delete from claims where donation_id in (select d.id from donations d join donors o "
                     "on o.id = d.donor_id where o.telegram_chat_id = %s)", (CHAT,))
        conn.execute("delete from donations where donor_id in (select id from donors where telegram_chat_id = %s)", (CHAT,))
        conn.execute("delete from donors where telegram_chat_id = %s", (CHAT,))


@pytest.fixture(autouse=True)
def clean():
    cleanup()
    yield
    cleanup()


def run(*updates):
    async def go():
        fake = FakeTelegram()
        app = h.build_application("123:TEST", request=fake)
        await app.initialize()
        for u in updates:
            await app.process_update(Update.de_json(u, app.bot))
        await app.shutdown()
        return fake
    return asyncio.run(go())


def donor():
    return repo.create_donor(CHAT, "Lister Bakery", "business", 10.7250, 122.5575)


def post(d, food, **kw):
    return repo.create_donation(donor=d, photo_url=None, food_type=food, quantity="10 pcs", est_kg=1,
                                lat=10.7250, lng=122.5575, good_for_hours=4, **kw)["id"]


def sent(fake, endpoint):
    return [p for e, p in fake.sent if e == endpoint]


def test_no_profile_and_no_listings():
    assert "haven't shared food yet" in sent(run(msg("/mylistings")), "sendMessage")[0]["text"]
    donor()
    assert "no live listings" in sent(run(msg("/mylistings")), "sendMessage")[0]["text"]


def test_lists_open_sale_and_claimed_with_buttons_only_for_unclaimed():
    d = donor()
    open_id = post(d, "Pandesal")
    post(d, "Ensaymada", listing_type="sale", price=80)
    claimed_id = post(d, "Lumpia")
    repo.claim_donation(str(claimed_id), JARO)

    out = sent(run(msg("/mylistings")), "sendMessage")[0]
    text, keyboard = out["text"], out["reply_markup"]
    assert "Pandesal" in text and "Ensaymada" in text and "₱80" in text
    assert "Claimed by *Bayanihan Pantry Jaro*" in text
    buttons = [b["callback_data"] for row in keyboard["inline_keyboard"] for b in row]
    assert len(buttons) == 2 and f"gone:{open_id}" in buttons and f"gone:{claimed_id}" not in buttons


def test_mark_as_gone_withdraws_and_refreshes_list():
    d = donor()
    gone_id = post(d, "Pandesal")
    post(d, "Turon")
    fake = run(tap(f"gone:{gone_id}"))
    with db.connect() as conn:
        assert conn.execute("select status from donations where id = %s", (gone_id,)).fetchone()["status"] == "withdrawn"
    assert "Taken down" in sent(fake, "answerCallbackQuery")[0]["text"]
    edited = sent(fake, "editMessageText")[0]["text"]
    assert "Turon" in edited and "Pandesal" not in edited


def test_gone_after_someone_claimed_it_explains():
    d = donor()
    did = post(d, "Pandesal")
    repo.claim_donation(str(did), JARO)  # claim wins the race
    fake = run(tap(f"gone:{did}"))
    answer = sent(fake, "answerCallbackQuery")[0]
    assert "Already claimed by Bayanihan Pantry Jaro" in answer["text"] and answer.get("show_alert")


def test_only_the_donor_can_mark_gone():
    fake = run(tap("gone:00000000-0000-0000-0000-000000000000"))  # this chat is no donor
    assert "Only the donor" in sent(fake, "answerCallbackQuery")[0]["text"]
