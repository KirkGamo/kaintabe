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
            m["entities"] = [{"type": "bot_command", "offset": 0, "length": len(text.split()[0])}]
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
        # parked demo roles have no chat link any more; find them through demo_parked
        parked = conn.execute("delete from demo_parked where chat_id in (%s, %s) returning kind, row_id",
                              (A, B)).fetchall()
        for p in parked:
            if p["kind"] == "donor":
                conn.execute("delete from donors where id = %s", (p["row_id"],))
            elif str(p["row_id"]) == JARO:
                conn.execute("update recipients set telegram_chat_id = %s where id = %s", (A, JARO))
            else:
                conn.execute("delete from recipients where id = %s", (p["row_id"],))
        test_listings = ("select d.id from donations d join donors o on o.id = d.donor_id"
                         " where o.telegram_chat_id in (%s, %s) or d.food_type like 'Welcome test%%'")
        conn.execute(f"delete from claims where donation_id in ({test_listings})", (A, B))
        conn.execute(f"delete from donations where id in ({test_listings})", (A, B))
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


def test_individual_on_flash_list_can_also_register_an_org():
    """Regression: the same Telegram account may be an individual AND an org rep (was a unique-index crash)."""
    run(msg(A, "/start"), tap(A, "role:recipient"), tap(A, "indname:tg"), msg(A, location=(10.7300, 122.5600)))  # joins flash list
    fake = run(msg(A, "/start"), tap(A, "role:org"), tap(A, "orglink:new"), msg(A, "Jaro Youth Kitchen"),
               tap(A, "okind:pantry"), msg(A, location=(10.7245, 122.5570)), tap(A, "orad:3"),
               msg(A, "24 hours"), msg(A, "40 meals/day"))
    assert not any("Something went wrong" in t for t in texts(fake))
    assert org_row(A)["name"] == "Jaro Youth Kitchen"
    with db.connect() as conn:
        kinds = {r["type"] for r in conn.execute(
            "select type from recipients where telegram_chat_id = %s and via_bot = %s", (A, BOT))}
    assert kinds == {"individual", "partner_org"}


# --- /demo role switch -------------------------------------------------------------------

def all_three_roles(chat):
    """Donor + individual + linked seeded org (Jaro) for one chat, like the presenter's account."""
    with db.connect() as conn:
        conn.execute("insert into donors (name, type, lat, lng, telegram_chat_id, pledged_at) "
                     "values ('Test Lugawan', 'business', 10.729, 122.5576, %s, now())", (chat,))
    run(msg(chat, "/start"), tap(chat, "role:recipient"), tap(chat, "indname:tg"), msg(chat, location=(10.7300, 122.5600)))
    run(msg(chat, "/start"), tap(chat, "role:org"), tap(chat, f"orglink:{JARO}"))


def active(chat):
    return {k: r["active"] for k, r in h.repo.role_summary(chat, BOT).items()}


def demo(chat, *extra):
    return run(*extra) if extra else None


def test_demo_switch_parks_and_restores_roles():
    all_three_roles(A)
    demo(A, msg(A, "/demo org"))
    assert active(A) == {"donor": None, "org": "Bayanihan Pantry Jaro", "individual": None}
    assert JARO not in [str(o["id"]) for o in h.repo.unlinked_orgs()]  # parked orgs aren't up for grabs

    fake = demo(A, msg(A, "/demo donor"))
    assert active(A) == {"donor": "Test Lugawan", "org": None, "individual": None}
    assert any("only the donor *Test Lugawan*" in t for t in texts(fake))

    demo(A, msg(A, "/demo fresh"))
    assert active(A) == {"donor": None, "org": None, "individual": None}
    fake = run(msg(A, "/start"))  # a brand-new user again: the full role question
    assert any("What brings you here?" in t for t in texts(fake))

    demo(A, msg(A, "/demo all"))
    assert active(A) == {"donor": "Test Lugawan", "org": "Bayanihan Pantry Jaro", "individual": "Org"}


def test_demo_individual_is_switched_back_on():
    all_three_roles(A)
    run(msg(A, "/stop"))
    demo(A, msg(A, "/demo individual"))
    assert h.repo.get_individual(A, BOT)["active"] is True


def test_demo_role_never_registered_says_how_to_register():
    fake = demo(A, msg(A, "/demo org"))
    assert any("no partner org profile yet" in t for t in texts(fake))


def test_demo_mid_conversation_ends_the_draft():
    """/demo while the bot waits for an org name must not let the next text become that name."""
    fake = demo(A, msg(A, "/start"), tap(A, "role:org"), tap(A, "orglink:new"), msg(A, "/demo donor"),
                msg(A, "Not An Org Name"))
    assert org_row(A) is None
    assert not any("Not An Org Name" in t for t in texts(fake))


def test_demo_is_open_to_everyone_but_only_touches_own_roles():
    all_three_roles(B)
    with db.connect() as conn:
        conn.execute("insert into donors (name, type, lat, lng, telegram_chat_id, pledged_at) "
                     "values ('Test A', 'household', 10.729, 122.5576, %s, now())", (A,))
    fake = demo(A, msg(A, "/demo fresh"))
    assert any("every role set aside" in t for t in texts(fake))
    assert active(A)["donor"] is None
    assert active(B) == {"donor": "Test Lugawan", "org": "Bayanihan Pantry Jaro", "individual": "Org"}

    fake = demo(A, msg(A, "/demo"))  # no argument: explains the switch to anyone
    assert any("Try every role" in t for t in texts(fake))


def test_error_message_does_not_blame_connection_for_bugs():
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    for err, expected in ((KeyError("org"), "our mistake"), (h.NetworkError("timeout"), "connection hiccup")):
        reply = AsyncMock()
        with patch.object(Update, "effective_message", new=SimpleNamespace(reply_text=reply)):
            asyncio.run(h.on_error(Update(update_id=1), SimpleNamespace(error=err)))
        assert expected in reply.await_args.args[0]


# --- /start welcomes -----------------------------------------------------------------------

def welcome_listing(conn, donor_id=None, status="posted"):
    """A listing next to Jaro (inside its 2 km start radius); food name marks it for cleanup."""
    from tests.conftest import insert_donation
    extra = {"donor_id": donor_id, "donor_name": "Test Lugawan"} if donor_id else {}
    return insert_donation(conn, food_type="Welcome test pancit", est_kg=2, status=status, **extra)


def test_new_user_welcome_explains_and_shows_numbers():
    with db.connect() as conn:  # one confirmed pickup, so the totals aren't zero even on an empty database
        done = welcome_listing(conn, status="completed")
        conn.execute("insert into claims (donation_id, recipient_id, confirmed_at) values (%s, %s, now())", (done, JARO))
    fake = run(msg(A, "/start"))
    text = next(t for t in texts(fake) if "What brings you here?" in t)
    assert "*How it works*" in text and "1️⃣ A donor sends a photo" in text
    assert "kg rescued" in text


def test_returning_donor_sees_own_impact_and_live_listings():
    with db.connect() as conn:
        donor = conn.execute("insert into donors (name, type, lat, lng, telegram_chat_id, pledged_at) values "
                             "('Test Lugawan', 'business', 10.725, 122.5575, %s, now()) returning id", (A,)).fetchone()["id"]
        done = welcome_listing(conn, donor, status="completed")
        conn.execute("insert into claims (donation_id, recipient_id, confirmed_at) values (%s, %s, now())", (done, JARO))
        welcome_listing(conn, donor)
    text = next(t for t in texts(run(msg(A, "/start"))) if "Welcome back" in t)
    assert "💚 Your impact: 1 pickup · 2 kg ≈ 5 meals" in text
    assert "📦 Live now: 1 listing" in text


def test_new_donor_welcome_leaves_out_empty_numbers():
    with db.connect() as conn:
        conn.execute("insert into donors (name, type, lat, lng, telegram_chat_id, pledged_at) values "
                     "('Test Lugawan', 'business', 10.725, 122.5575, %s, now())", (A,))
    text = next(t for t in texts(run(msg(A, "/start"))) if "Welcome back" in t)
    assert "Your impact" not in text and "Live now" not in text and "send a photo" in text


def test_returning_org_sees_food_near_and_waiting_pickup():
    run(msg(A, "/start"), tap(A, "role:org"), tap(A, f"orglink:{JARO}"))
    with db.connect() as conn:
        welcome_listing(conn)
        waiting = welcome_listing(conn, status="claimed")
        conn.execute("insert into claims (donation_id, recipient_id) values (%s, %s)", (waiting, JARO))
    text = next(t for t in texts(run(msg(A, "/start"))) if "Welcome back" in t)
    assert "🍲 Near you now:" in text and "within 6 km" in text
    assert "🚚 Waiting for your pickup: Welcome test pancit" in text


def test_returning_individual_is_recognized_not_asked_the_role_again():
    run(msg(A, "/start"), tap(A, "role:recipient"), msg(A, "Ana Typed"), msg(A, location=(10.7300, 122.5600)))
    text = texts(run(msg(A, "/start")))[-1]
    assert "Welcome back, Ana Typed!" in text and "You're on the flash-offer list" in text

    run(msg(A, "/stop"))
    fake = run(msg(A, "/start"))
    assert "paused" in texts(fake)[-1]
    offered = [b.get("callback_data") for e, p in fake.sent if e == "sendMessage" and "reply_markup" in p
               for row in p["reply_markup"]["inline_keyboard"] for b in row]
    assert "role:recipient" in offered
