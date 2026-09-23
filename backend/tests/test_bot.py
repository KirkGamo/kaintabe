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
def no_ai():
    """Bot tests never call the real AI; individual tests override the return value."""
    with (
        patch.object(h.ai_intake, "parse_food_photo", new_callable=AsyncMock, return_value=None) as ai,
        patch.object(h.ai_intake, "enabled", return_value=True),
    ):
        yield ai


@pytest.fixture(autouse=True)
def clean_test_donor():
    cleanup()
    yield
    cleanup()


def onboard(ctx, name="Test Bakery", location=(10.7141, 122.5519), donor_type="household"):
    assert run(h.start(update_msg(text="/start"), ctx)) == h.ROLE
    assert run(h.chose_role(update_tap("role:donor"), ctx)) == h.NAME
    assert run(h.got_name(update_msg(text=name), ctx)) == h.DONOR_TYPE
    assert run(h.chose_type(update_tap(f"type:{donor_type}"), ctx)) == h.LOCATION
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
    u = onboard(ctx, donor_type="business")
    assert "all set" in last_reply(u)

    with db.connect() as conn:
        donor = conn.execute("select * from donors where telegram_chat_id = %s", (CHAT_ID,)).fetchone()
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

    d = fetch_donation()
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

    d = fetch_donation()
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
    kinds = [getattr(c, "name", None) or type(c).__name__ for c in app.handlers[0]]
    # conversations first; catch-alls last so they only see what no conversation handled
    assert kinds == ["onboarding", "posting", "CommandHandler", "CallbackQueryHandler", "MessageHandler"]


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


def ai_listing(**overrides):
    fields = dict(is_food=True, food_type="Pandesal", quantity="about 30 pieces", est_kg=1.5, good_for_hours=8,
                  allergens=["milk", "wheat"], suggested_price_php=60, confidence="high")
    return h.ai_intake.FoodListing(**{**fields, **overrides})


def fetch_donation():
    with db.connect() as conn:
        return conn.execute(
            "select d.* from donations d join donors o on o.id = d.donor_id where o.telegram_chat_id = %s", (CHAT_ID,)
        ).fetchone()


@patch.object(h.storage, "upload_photo", new_callable=AsyncMock, return_value="https://example.com/ai.jpg")
def test_ai_intake_confirmed_skips_questions(upload, no_ai):
    no_ai.return_value = ai_listing()
    ctx = make_context()
    onboard(ctx)

    u = update_msg(photo=True, caption="pandesal from this morning")
    assert run(h.got_photo(u, ctx)) == h.AI_CONFIRM
    no_ai.assert_awaited_once_with(b"\xff\xd8fakejpeg", "pandesal from this morning")
    summary = last_reply(u)
    assert "Pandesal" in summary and "about 30 pieces" in summary and "8 hrs" in summary and "milk, wheat" in summary

    assert run(h.chose_ai(update_tap("ai:ok"), ctx)) == h.PICKUP  # straight to pickup: no manual questions
    assert run(h.chose_pickup(update_tap("loc:saved"), ctx)) == h.SAFETY
    pass_safety(ctx)

    d = fetch_donation()
    assert (d["food_type"], d["quantity"], float(d["est_kg"])) == ("Pandesal", "about 30 pieces", 1.5)
    assert d["allergens"] == ["milk", "wheat"] and d["ai_assisted"] is True and float(d["suggested_price"]) == 60
    upload.assert_awaited_once_with("donation-photos", b"\xff\xd8fakejpeg")
    left = d["expires_at"] - datetime.now(timezone.utc)
    assert timedelta(hours=7, minutes=58) < left <= timedelta(hours=8)


@patch.object(h.storage, "upload_photo", new_callable=AsyncMock, return_value="https://example.com/ai.jpg")
def test_ai_intake_fix_details_falls_back_to_manual(upload, no_ai):
    no_ai.return_value = ai_listing(food_type="Ensaymada")
    ctx = make_context()
    onboard(ctx)
    run(h.got_photo(update_msg(photo=True), ctx))
    assert run(h.chose_ai(update_tap("ai:edit"), ctx)) == h.FOOD
    run(h.got_food(update_msg(text="Spanish bread"), ctx))
    run(h.got_quantity(update_msg(text="12 pcs"), ctx))
    run(h.chose_weight(update_tap("kg:0"), ctx))
    run(h.chose_hours(update_tap("hrs:4"), ctx))
    run(h.chose_pickup(update_tap("loc:saved"), ctx))
    pass_safety(ctx)

    d = fetch_donation()
    assert d["food_type"] == "Spanish bread" and d["ai_assisted"] is False and d["allergens"] is None


def test_ai_not_food_asks_manually(no_ai):
    no_ai.return_value = ai_listing(is_food=False)
    ctx = make_context()
    onboard(ctx)
    u = update_msg(photo=True)
    assert run(h.got_photo(u, ctx)) == h.FOOD
    replies = [c.args[0] for c in u.effective_message.reply_text.call_args_list]
    assert any("doesn't look like food" in r for r in replies)


def test_ai_unavailable_uses_caption_as_before(no_ai):
    no_ai.return_value = None  # no key / timeout / API error
    ctx = make_context()
    onboard(ctx)
    assert run(h.got_photo(update_msg(photo=True, caption="Turon"), ctx)) == h.QUANTITY
    assert ctx.user_data["draft"]["food_type"] == "Turon"


def test_ai_summary_escapes_markdown_and_flags_low_confidence():
    text = h.ai_summary(ai_listing(food_type="Pan_de*sal", confidence="low", allergens=[]))
    assert r"Pan\_de\*sal" in text and "not fully sure" in text and "May contain" not in text


def test_no_ai_key_goes_straight_to_manual_silently():
    ctx = make_context()
    onboard(ctx)
    u = update_msg(photo=True)
    with patch.object(h.ai_intake, "enabled", return_value=False):
        assert run(h.got_photo(u, ctx)) == h.FOOD
    replies = [c.args[0] for c in u.effective_message.reply_text.call_args_list]
    assert not any("Looking at your photo" in r for r in replies)


# --- sale tier -------------------------------------------------------------

def details_as_business(ctx, ai=False):
    """Business donor fills details; returns the state after the details step."""
    onboard(ctx, donor_type="business")
    if ai:
        run(h.got_photo(update_msg(photo=True), ctx))
        return run(h.chose_ai(update_tap("ai:ok"), ctx))
    run(h.got_photo(update_msg(photo=True, caption="Ensaymada"), ctx))
    run(h.got_quantity(update_msg(text="12 pcs"), ctx))
    run(h.chose_weight(update_tap("kg:0"), ctx))
    return run(h.chose_hours(update_tap("hrs:8"), ctx))


@patch.object(h.storage, "upload_photo", new_callable=AsyncMock, return_value="https://example.com/s.jpg")
def test_business_sells_with_typed_price(upload):
    ctx = make_context()
    assert details_as_business(ctx) == h.LISTING_TYPE
    u = update_tap("lt:sale")
    assert run(h.chose_listing_type(u, ctx)) == h.PRICE
    assert "Type a price" in last_reply(u)  # no AI suggestion without AI

    assert run(h.got_price(update_msg(text="cheap po"), ctx)) is None  # re-ask, stay
    assert run(h.got_price(update_msg(text="₱1,200"), ctx)) == h.PICKUP
    run(h.chose_pickup(update_tap("loc:saved"), ctx))
    done = pass_safety(ctx)
    assert "For sale at ₱1200" in last_reply(done)

    d = fetch_donation()
    assert d["listing_type"] == "sale"
    assert float(d["original_price"]) == 1200
    assert 1 <= float(d["current_price"]) <= 1200  # the live cron may already have ticked it down


@patch.object(h.storage, "upload_photo", new_callable=AsyncMock, return_value="https://example.com/s.jpg")
def test_business_taps_ai_suggested_price(upload, no_ai):
    no_ai.return_value = ai_listing(suggested_price_php=60)
    ctx = make_context()
    assert details_as_business(ctx, ai=True) == h.LISTING_TYPE
    u = update_tap("lt:sale")
    run(h.chose_listing_type(u, ctx))
    keyboard = u.effective_message.reply_text.call_args.kwargs["reply_markup"].inline_keyboard
    assert keyboard[0][0].callback_data == "price:60"

    assert run(h.got_price(update_tap("price:60"), ctx)) == h.PICKUP
    run(h.chose_pickup(update_tap("loc:saved"), ctx))
    pass_safety(ctx)
    assert float(fetch_donation()["original_price"]) == 60  # current_price may already be ticking down


@patch.object(h.storage, "upload_photo", new_callable=AsyncMock, return_value="https://example.com/s.jpg")
def test_business_can_still_donate_free(upload):
    ctx = make_context()
    details_as_business(ctx)
    assert run(h.chose_listing_type(update_tap("lt:donation"), ctx)) == h.PICKUP
    run(h.chose_pickup(update_tap("loc:saved"), ctx))
    pass_safety(ctx)
    d = fetch_donation()
    assert d["listing_type"] == "donation" and d["original_price"] is None and d["current_price"] is None


def test_price_parsing():
    assert h.parse_price("₱1,200 pesos") == 1200
    assert h.parse_price("P85.50") == 86
    assert h.parse_price("120") == 120
    assert h.parse_price("free") is None
    assert h.parse_price("0") is None
