"""R3a: partner orgs sign up / link through the bot, and 'Open map' buttons (fake Telegram, real DB)."""
import asyncio
import itertools
from unittest.mock import patch

import pytest
from telegram import Update

from app import db
from app.bot import handlers as h
from app.services import telegram as tg_out
from tests.test_routing import FakeTelegram

A, B = -440001, -440002
JARO = "00000000-0000-0000-0000-00000000a001"
BOT = "test_bot"  # FakeTelegram's getMe username
MAP = "https://kaintabe.example.app"
_ids = itertools.count(1)


def msg(chat, text=None, location=None):
    m = {"message_id": next(_ids), "date": 0, "chat": {"id": chat, "type": "private"},
         "from": {"id": chat, "is_bot": False, "first_name": "Org"}}
    if text is not None:
        m["text"] = text
        if text.startswith("/"):
            m["entities"] = [{"type": "bot_command", "offset": 0, "length": len(text)}]
    if location:
        m["location"] = {"latitude": location[0], "longitude": location[1]}
    return {"update_id": next(_ids), "message": m}


def tap(chat, data):
    return {"update_id": next(_ids), "callback_query": {
        "id": str(next(_ids)), "from": {"id": chat, "is_bot": False, "first_name": "Org"},
        "chat_instance": "x", "data": data,
        "message": {"message_id": 1, "date": 0, "chat": {"id": chat, "type": "private"}, "text": "question?"}}}


def cleanup():
    with db.connect() as conn:
        conn.execute("delete from recipients where telegram_chat_id in (%s, %s) and id <> %s", (A, B, JARO))
        conn.execute("delete from donors where telegram_chat_id in (%s, %s)", (A, B))
        conn.execute("update recipients set telegram_chat_id = null, via_bot = null, review_status = 'approved' "
                     "where id = %s and telegram_chat_id in (%s, %s)", (JARO, A, B))


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


def texts(fake):
    return [p.get("text", "") for e, p in fake.sent if e == "sendMessage"]


def org_row(chat):
    with db.connect() as conn:
        return conn.execute("select * from recipients where type = 'partner_org' and telegram_chat_id = %s "
                            "and via_bot = %s", (chat, BOT)).fetchone()


def test_register_new_org():
    fake = run(msg(A, "/start"), tap(A, "role:org"), tap(A, "orglink:new"), msg(A, "Molo Soup Kitchen"),
               tap(A, "okind:community_kitchen"), msg(A, location=(10.6975, 122.5446)), tap(A, "orad:5"),
               msg(A, "8:00–18:00"), msg(A, "80 meals/day"))
    org = org_row(A)
    assert org["name"] == "Molo Soup Kitchen" and org["org_kind"] == "community_kitchen"
    assert (org["service_radius_m"], org["hours"], org["capacity"]) == (5000, "8:00–18:00", "80 meals/day")
    assert org["review_status"] == "pending_review" and org["verified"] is False
    assert any("Pending review" in t and "5 km" in t for t in texts(fake))


def test_link_seeded_org_first_come():
    fake = run(msg(A, "/start"), tap(A, "role:org"))
    offered = [b["callback_data"] for p in fake.sent if p[0] == "sendMessage" and "reply_markup" in p[1]
               for row in p[1]["reply_markup"]["inline_keyboard"] for b in row if "callback_data" in b]
    assert f"orglink:{JARO}" in offered and "orglink:new" in offered

    run(msg(A, "/start"), tap(A, "role:org"), tap(A, f"orglink:{JARO}"))
    assert str(org_row(A)["id"]) == JARO and org_row(A)["review_status"] == "pending_review"

    # B can no longer see or take Jaro
    fake = run(msg(B, "/start"), tap(B, "role:org"), tap(B, f"orglink:{JARO}"))
    answers = [p for e, p in fake.sent if e == "answerCallbackQuery"]
    assert any("already linked" in a.get("text", "") for a in answers)
    assert org_row(B) is None


def test_start_welcomes_back_linked_org():
    run(msg(A, "/start"), tap(A, "role:org"), tap(A, f"orglink:{JARO}"))
    fake = run(msg(A, "/start"))
    assert any("Welcome back, *Bayanihan Pantry Jaro*" in t for t in texts(fake))


def test_open_map_buttons_only_with_https_url():
    with patch.object(h.settings, "web_url", MAP):
        fake = run(msg(A, "/start"))
    web_apps = [b["web_app"]["url"] for e, p in fake.sent if e == "sendMessage" and "reply_markup" in p
                for row in p["reply_markup"]["inline_keyboard"] for b in row if "web_app" in b]
    assert MAP in web_apps

    with patch.object(h.settings, "web_url", ""), patch.object(h.settings, "frontend_origin", "http://localhost:5173"):
        fake = run(msg(A, "/start"))
    assert not any("web_app" in b for e, p in fake.sent if "reply_markup" in p
                   for row in p["reply_markup"]["inline_keyboard"] for b in row)


def test_map_url_prefers_web_url_then_https_origin():
    s = h.settings
    with patch.object(s, "web_url", ""), patch.object(s, "frontend_origin", "http://localhost:5173,https://x.vercel.app/"):
        assert s.map_url == "https://x.vercel.app"
    with patch.object(s, "web_url", "https://tunnel.trycloudflare.com/"):
        assert s.map_url == "https://tunnel.trycloudflare.com"
    with patch.object(s, "web_url", ""), patch.object(s, "frontend_origin", "http://localhost:5173"):
        assert s.map_url is None


def test_donor_notifications_carry_map_button():
    with patch.object(tg_out.settings, "web_url", MAP):
        assert tg_out.map_markup()["inline_keyboard"][0][0]["web_app"]["url"] == MAP


def test_donor_can_also_register_an_org_from_welcome_back():
    """A registered donor's /start offers the org sign-up (before, only brand-new users saw the role menu)."""
    with db.connect() as conn:
        conn.execute("insert into donors (name, type, lat, lng, telegram_chat_id, pledged_at) "
                     "values ('Test Lugawan', 'business', 10.729, 122.5576, %s, now())", (A,))
    fake = run(msg(A, "/start"))
    offered = [b.get("callback_data") for e, p in fake.sent if e == "sendMessage" and "reply_markup" in p
               for row in p["reply_markup"]["inline_keyboard"] for b in row]
    assert "role:org" in offered

    fake = run(msg(A, "/start"), tap(A, "role:org"), tap(A, "orglink:new"), msg(A, "Jaro Lugaw Kitchen"),
               tap(A, "okind:community_kitchen"), msg(A, location=(10.7290, 122.5576)), tap(A, "orad:5"),
               msg(A, "7:00–19:00"), msg(A, "50 meals/day"))
    assert not any("Something went wrong" in t for t in texts(fake))
    assert org_row(A)["name"] == "Jaro Lugaw Kitchen"
    assert any("also a donor" in t for t in texts(fake))  # the org welcome knows they still donate


def test_individual_on_flash_list_can_also_register_an_org():
    """Regression: the same Telegram account may be an individual AND an org rep (was a unique-index crash)."""
    run(msg(A, "/start"), tap(A, "role:recipient"), msg(A, location=(10.7300, 122.5600)))  # joins flash list
    fake = run(msg(A, "/start"), tap(A, "role:org"), tap(A, "orglink:new"), msg(A, "Jaro Youth Kitchen"),
               tap(A, "okind:pantry"), msg(A, location=(10.7245, 122.5570)), tap(A, "orad:3"),
               msg(A, "24 hours"), msg(A, "40 meals/day"))
    assert not any("Something went wrong" in t for t in texts(fake))
    assert org_row(A)["name"] == "Jaro Youth Kitchen"
    with db.connect() as conn:
        kinds = {r["type"] for r in conn.execute(
            "select type from recipients where telegram_chat_id = %s and via_bot = %s", (A, BOT))}
    assert kinds == {"individual", "partner_org"}


def test_error_message_does_not_blame_connection_for_bugs():
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    for err, expected in ((KeyError("org"), "our mistake"), (h.NetworkError("timeout"), "connection hiccup")):
        reply = AsyncMock()
        with patch.object(Update, "effective_message", new=SimpleNamespace(reply_text=reply)):
            asyncio.run(h.on_error(Update(update_id=1), SimpleNamespace(error=err)))
        assert expected in reply.await_args.args[0]
