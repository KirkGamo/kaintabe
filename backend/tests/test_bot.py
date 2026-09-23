"""Drive the donor conversations with mock Telegram updates (real DB, mocked Telegram + storage)."""
import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app import db
from app.bot import handlers as h
from app.config import settings
from app.services import storage

CHAT_ID = -990001  # fake chat id reserved for tests


def run(coro):
    return asyncio.run(coro)


def make_context():
    tg_file = SimpleNamespace(download_as_bytearray=AsyncMock(return_value=bytearray(b"\xff\xd8fakejpeg")))
    return SimpleNamespace(user_data={}, bot=SimpleNamespace(get_file=AsyncMock(return_value=tg_file)))


def message(text=None, location=None, photo=False, caption=None):
    return SimpleNamespace(
        text=text,
        caption=caption,
        location=SimpleNamespace(latitude=location[0], longitude=location[1]) if location else None,
        photo=[SimpleNamespace(file_id="small"), SimpleNamespace(file_id="large")] if photo else [],
        reply_text=AsyncMock(),
    )


def update_msg(**kw):
    msg = message(**kw)
    return SimpleNamespace(effective_chat=SimpleNamespace(id=CHAT_ID), effective_message=msg, callback_query=None)


def update_tap(data, question="question?"):
    msg = message(text=question)
    query = SimpleNamespace(data=data, message=msg, answer=AsyncMock(), edit_message_text=AsyncMock())
    return SimpleNamespace(effective_chat=SimpleNamespace(id=CHAT_ID), effective_message=msg, callback_query=query)


def last_reply(update):
    return update.effective_message.reply_text.call_args.args[0]


def cleanup():
    with db.connect() as conn:
        conn.execute(
            "delete from donations where donor_id in (select id from donors where telegram_chat_id = %s)", (CHAT_ID,)
        )
        conn.execute("delete from donors where telegram_chat_id = %s", (CHAT_ID,))


@pytest.fixture(autouse=True)
def clean_test_donor():
    cleanup()
    yield
    cleanup()


def onboard(ctx, name="Test Bakery", location=(10.7141, 122.5519)):
    assert run(h.start(update_msg(text="/start"), ctx)) == h.ROLE
    assert run(h.chose_role(update_tap("role:donor"), ctx)) == h.NAME
    assert run(h.got_name(update_msg(text=name), ctx)) == h.DONOR_TYPE
    assert run(h.chose_type(update_tap("type:business"), ctx)) == h.LOCATION
    assert run(h.location_expected(update_msg(text="Jaro"), ctx)) is None  # typed text: stay, re-prompt
    assert run(h.got_location(update_msg(location=location), ctx)) == h.PLEDGE
    u = update_tap("pledge:yes")
    assert run(h.pledged(u, ctx)) == h.END
    return u


def pass_safety(ctx):
    """Answer Yes to every checklist question; returns the final update."""
    last = len(h.SAFETY_CHECKLIST) - 1
    for i in range(last):
        assert run(h.answered_safety(update_tap(f"safe:{i}:yes"), ctx)) == h.SAFETY
    u = update_tap(f"safe:{last}:yes")
    assert run(h.answered_safety(u, ctx)) == h.END
    return u


def start_post(ctx):
    """Onboard, then fill a draft up to the safety checklist."""
    onboard(ctx)
    run(h.got_photo(update_msg(photo=True, caption="Lumpia"), ctx))
    run(h.got_quantity(update_msg(text="20 pieces"), ctx))
    run(h.chose_weight(update_tap("kg:1"), ctx))
    run(h.chose_hours(update_tap("hrs:4"), ctx))
    return run(h.chose_pickup(update_tap("loc:saved"), ctx))


def donation_count():
    with db.connect() as conn:
        return conn.execute(
            "select count(*) n from donations d join donors o on o.id = d.donor_id where o.telegram_chat_id = %s",
            (CHAT_ID,),
        ).fetchone()["n"]


def test_onboarding_creates_donor():
    ctx = make_context()
    u = onboard(ctx)
    assert "all set" in last_reply(u)

    donor = db.connect().execute("select * from donors where telegram_chat_id = %s", (CHAT_ID,)).fetchone()
    assert donor["name"] == "Test Bakery"
    assert donor["type"] == "business"
    assert (donor["lat"], donor["lng"]) == (10.7141, 122.5519)
    assert donor["pledged_at"] is not None
    assert ctx.user_data == {}

    # /start again: recognized, no re-onboarding
    u = update_msg(text="/start")
    assert run(h.start(u, ctx)) == h.END
    assert "Welcome back" in last_reply(u)


def test_recipient_role_ends_politely():
    ctx = make_context()
    run(h.start(update_msg(text="/start"), ctx))
    u = update_tap("role:recipient")
    assert run(h.chose_role(u, ctx)) == h.END
    assert "coming soon" in last_reply(u)


def test_photo_before_onboarding_asks_for_start():
    u = update_msg(photo=True)
    assert run(h.got_photo(u, make_context())) == h.END
    assert "/start" in last_reply(u)


@patch.object(h.storage, "upload_photo", new_callable=AsyncMock, return_value="https://example.com/photo.jpg")
def test_post_with_caption_and_saved_location(upload):
    ctx = make_context()
    onboard(ctx)

    assert run(h.got_photo(update_msg(photo=True, caption="Pan_de*sal"), ctx)) == h.QUANTITY  # caption = food
    assert run(h.got_quantity(update_msg(text="30 pieces"), ctx)) == h.WEIGHT
    assert run(h.chose_weight(update_tap("kg:1"), ctx)) == h.HOURS
    assert run(h.chose_hours(update_tap("hrs:4"), ctx)) == h.PICKUP
    assert run(h.chose_pickup(update_tap("loc:saved"), ctx)) == h.SAFETY
    u = pass_safety(ctx)
    assert "Live now" in last_reply(u)

    ctx.bot.get_file.assert_awaited_once_with("large")  # largest photo size
    upload.assert_awaited_once()

    d = db.connect().execute(
        "select d.* from donations d join donors o on o.id = d.donor_id where o.telegram_chat_id = %s", (CHAT_ID,)
    ).fetchone()
    assert d["food_type"] == "Pan_de*sal"
    assert d["quantity"] == "30 pieces"
    assert float(d["est_kg"]) == 2
    assert (d["lat"], d["lng"]) == (10.7141, 122.5519)
    assert d["donor_name"] == "Test Bakery"
    assert d["photo_url"] == "https://example.com/photo.jpg"
    assert d["status"] == "posted"
    assert d["search_radius_m"] == 2000
    assert d["safety_checklist"] == {"hygienic": True, "safe_temperature": True, "contents_known": True}
    left = d["expires_at"] - datetime.now(timezone.utc)
    assert timedelta(hours=3, minutes=58) < left <= timedelta(hours=4)
    assert ctx.user_data == {}


@patch.object(h.storage, "upload_photo", new_callable=AsyncMock, return_value="https://example.com/p2.jpg")
def test_post_without_caption_and_new_location(upload):
    ctx = make_context()
    onboard(ctx)

    assert run(h.got_photo(update_msg(photo=True), ctx)) == h.FOOD
    assert run(h.got_food(update_msg(text="Chicken adobo"), ctx)) == h.QUANTITY
    assert run(h.got_quantity(update_msg(text="5 trays"), ctx)) == h.WEIGHT
    assert run(h.chose_weight(update_tap("kg:4"), ctx)) == h.HOURS
    assert run(h.chose_hours(update_tap("hrs:2"), ctx)) == h.PICKUP
    u = update_tap("loc:new")
    assert run(h.chose_pickup(u, ctx)) == h.PICKUP_NEW
    assert "📎" in last_reply(u)  # explains how to pick a spot other than current GPS
    assert run(h.got_pickup_location(update_msg(location=(10.6962, 122.5452)), ctx)) == h.SAFETY
    pass_safety(ctx)

    d = db.connect().execute(
        "select d.* from donations d join donors o on o.id = d.donor_id where o.telegram_chat_id = %s", (CHAT_ID,)
    ).fetchone()
    assert d["food_type"] == "Chicken adobo"
    assert float(d["est_kg"]) == 12
    assert (d["lat"], d["lng"]) == (10.6962, 122.5452)


@pytest.mark.parametrize("failing_index", range(len(h.SAFETY_CHECKLIST)))
@patch.object(h.storage, "upload_photo", new_callable=AsyncMock)
def test_safety_no_blocks_post(upload, failing_index):
    ctx = make_context()
    assert start_post(ctx) == h.SAFETY
    for i in range(failing_index):
        assert run(h.answered_safety(update_tap(f"safe:{i}:yes"), ctx)) == h.SAFETY
    u = update_tap(f"safe:{failing_index}:no")
    assert run(h.answered_safety(u, ctx)) == h.END

    _, _, reason = h.SAFETY_CHECKLIST[failing_index]
    assert reason in last_reply(u) and "not posted" in last_reply(u)
    upload.assert_not_awaited()  # nothing uploaded or saved
    assert donation_count() == 0
    assert ctx.user_data == {}


@patch.object(h.storage, "upload_photo", new_callable=AsyncMock, return_value="https://example.com/p3.jpg")
def test_safety_ignores_stale_button(upload):
    ctx = make_context()
    start_post(ctx)
    run(h.answered_safety(update_tap("safe:0:yes"), ctx))

    stale = update_tap("safe:0:no")  # tapping question 1's old "No" while on question 2
    assert run(h.answered_safety(stale, ctx)) is None  # stay on current question
    stale.callback_query.answer.assert_awaited_once_with("Please answer the latest question.")
    assert "draft" in ctx.user_data

    for i in (1, 2):
        run(h.answered_safety(update_tap(f"safe:{i}:yes"), ctx))
    assert donation_count() == 1


def test_markdown_escaping():
    assert h.md("Pan_de*sal") == r"Pan\_de\*sal"


def test_application_builds():
    app = h.build_application("123456:TEST")
    assert [c.name for c in app.handlers[0]] == ["onboarding", "posting"]


def test_storage_upload_roundtrip():
    """Real upload to the donation-photos bucket, public fetch, then delete."""
    url = run(storage.upload_photo("donation-photos", b"\xff\xd8test-bytes"))
    try:
        res = httpx.get(url)
        assert res.status_code == 200 and res.content == b"\xff\xd8test-bytes"
    finally:
        path = url.rsplit("/", 1)[1]
        httpx.delete(
            f"{settings.supabase_url}/storage/v1/object/donation-photos/{path}",
            headers={"Authorization": f"Bearer {settings.supabase_service_role_key}"},
        )
