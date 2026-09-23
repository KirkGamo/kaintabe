"""Telegram donor flows: onboarding (/start) and posting (send a photo).

Each handler is `async (update, context) -> next_state`, so tests can drive the
conversations with mock updates without talking to Telegram.
"""
import asyncio
import logging
import warnings

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    Update,
)
from telegram.helpers import escape_markdown
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from app.services import repo, storage

log = logging.getLogger(__name__)

# Conversations are tracked per chat on purpose (buttons belong to the current step)
warnings.filterwarnings("ignore", message=r"If 'per_message=False'")

# Onboarding states
ROLE, NAME, DONOR_TYPE, LOCATION, PLEDGE = range(5)
# Posting states
FOOD, QUANTITY, WEIGHT, HOURS, PICKUP, PICKUP_NEW = range(10, 16)

END = ConversationHandler.END

WEIGHT_OPTIONS = [("Under 1 kg", 0.5), ("1–3 kg", 2), ("3–5 kg", 4), ("5–10 kg", 7.5), ("10+ kg", 12)]
HOURS_OPTIONS = [2, 4, 8, 24]

PLEDGE_TEXT = (
    "🤝 *Donor safety pledge*\n\n"
    "• I will only share food that is safe to eat.\n"
    "• I will describe it honestly (contents, allergens, how long it keeps).\n"
    "• I will keep it stored properly until pickup.\n\n"
    "Recipients rely on this. Do you agree?"
)


def md(text: str) -> str:
    """Escape user-provided text for parse_mode="Markdown"."""
    return escape_markdown(str(text), version=1)


def buttons(rows: list[list[tuple[str, str]]]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton(t, callback_data=d) for t, d in row] for row in rows])


HERE_NOW = "📍 I'm there now — use my current location"


async def ask_location(update: Update, intro: str) -> None:
    """The keyboard button can only send current GPS; any other spot is picked via 📎 → Location."""
    await update.effective_message.reply_text(
        f"{intro}\n\n"
        "• *At the spot now?* Tap the button below.\n"
        "• *Somewhere else?* Tap 📎 → *Location*, drag the map to the pickup spot, "
        "then tap *Send selected location*.",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardMarkup(
            [[KeyboardButton(HERE_NOW, request_location=True)]], resize_keyboard=True, one_time_keyboard=True
        ),
    )


async def answer_choice(update: Update, chosen_label: str) -> None:
    """Acknowledge an inline button tap and freeze the question showing the choice."""
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(f"{query.message.text}\n\n✅ {chosen_label}")


# ---------------------------------------------------------------------------
# Onboarding
# ---------------------------------------------------------------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    donor = await asyncio.to_thread(repo.get_donor_by_chat, update.effective_chat.id)
    if donor:
        await update.effective_message.reply_text(
            f"Welcome back, {md(donor['name'])}! 👋\n\n"
            "To share food, just *send a photo* of it here.\n"
            "Send /profile to update your details.",
            parse_mode="Markdown",
        )
        return END
    return await ask_role(update, context)


async def ask_role(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.effective_message.reply_text(
        "🍱 *KainTabe — food rescue*\n\n"
        "Surplus food gets matched to nearby community kitchens before it spoils.\n\n"
        "What brings you here?",
        parse_mode="Markdown",
        reply_markup=buttons([[("I have food to share", "role:donor")], [("I need food", "role:recipient")]]),
    )
    return ROLE


async def chose_role(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    role = update.callback_query.data.split(":")[1]
    if role == "recipient":
        await answer_choice(update, "I need food")
        await update.effective_message.reply_text(
            "Thank you for reaching out 💚\n\n"
            "Community kitchens and pantries are onboarded by our team. "
            "Individual sign-up for last-minute food offers is coming soon."
        )
        return END
    await answer_choice(update, "I have food to share")
    await update.effective_message.reply_text(
        "Great! Let's set up your donor profile (takes 30 seconds).\n\n"
        "What name should recipients see? (e.g. your business or \"Household in Jaro\")"
    )
    return NAME


async def got_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["profile"] = {"name": update.effective_message.text.strip()[:80]}
    await update.effective_message.reply_text(
        "Are you a business or a household?",
        reply_markup=buttons([[("🏪 Business", "type:business"), ("🏠 Household", "type:household")]]),
    )
    return DONOR_TYPE


async def chose_type(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    type_ = update.callback_query.data.split(":")[1]
    context.user_data["profile"]["type"] = type_
    await answer_choice(update, type_.capitalize())
    await ask_location(
        update, "Where is your usual pickup spot? (You can use a different spot for each donation later.)"
    )
    return LOCATION


async def got_location(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    loc = update.effective_message.location
    context.user_data["profile"].update(lat=loc.latitude, lng=loc.longitude)
    await update.effective_message.reply_text("📍 Got it.", reply_markup=ReplyKeyboardRemove())
    await update.effective_message.reply_text(
        PLEDGE_TEXT, parse_mode="Markdown", reply_markup=buttons([[("✅ I pledge", "pledge:yes")]])
    )
    return PLEDGE


async def location_expected(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int | None:
    await ask_location(update, "I need a map location for this (typed addresses aren't supported yet).")
    return None  # stay in the current state


async def pledged(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    p = context.user_data.pop("profile")
    await answer_choice(update, "Pledged")
    await asyncio.to_thread(repo.create_donor, update.effective_chat.id, p["name"], p["type"], p["lat"], p["lng"])
    await update.effective_message.reply_text(
        f"🎉 You're all set, {md(p['name'])}!\n\n"
        "*How to donate:* just send a photo of the food here. "
        "I'll ask a few quick questions, then nearby community kitchens see it live on the map "
        "with a countdown — the nearest one claims it and comes to pick it up.\n\n"
        "Try it now: send a photo 📸",
        parse_mode="Markdown",
    )
    return END


# ---------------------------------------------------------------------------
# Posting a donation
# ---------------------------------------------------------------------------

async def got_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    msg = update.effective_message
    donor = await asyncio.to_thread(repo.get_donor_by_chat, update.effective_chat.id)
    if not donor:
        await msg.reply_text("Welcome! Let's set up your donor profile first — send /start.")
        return END

    context.user_data["draft"] = {"photo_file_id": msg.photo[-1].file_id}  # largest size
    context.user_data["donor"] = donor

    caption = (msg.caption or "").strip()
    if caption:
        context.user_data["draft"]["food_type"] = caption[:120]
        await msg.reply_text(f"📸 Thanks! Food: *{md(caption[:120])}*", parse_mode="Markdown")
        return await ask_quantity(update, context)

    await msg.reply_text("📸 Thanks! What food is it? (e.g. \"Pandesal\", \"Chicken adobo with rice\")")
    return FOOD


async def got_food(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["draft"]["food_type"] = update.effective_message.text.strip()[:120]
    return await ask_quantity(update, context)


async def ask_quantity(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.effective_message.reply_text("How much is there? (e.g. \"30 pieces\", \"5 trays\", \"10 packs\")")
    return QUANTITY


async def got_quantity(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["draft"]["quantity"] = update.effective_message.text.strip()[:80]
    await update.effective_message.reply_text(
        "Roughly how heavy is it all together?",
        reply_markup=buttons(
            [[(label, f"kg:{i}") for i, (label, _) in enumerate(WEIGHT_OPTIONS[:3])],
             [(label, f"kg:{i + 3}") for i, (label, _) in enumerate(WEIGHT_OPTIONS[3:])]]
        ),
    )
    return WEIGHT


async def chose_weight(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    label, kg = WEIGHT_OPTIONS[int(update.callback_query.data.split(":")[1])]
    context.user_data["draft"]["est_kg"] = kg
    await answer_choice(update, label)
    await update.effective_message.reply_text(
        "⏱ How long will it stay good to eat?",
        reply_markup=buttons([[(f"{h} hrs", f"hrs:{h}") for h in HOURS_OPTIONS]]),
    )
    return HOURS


async def chose_hours(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    hours = int(update.callback_query.data.split(":")[1])
    context.user_data["draft"]["good_for_hours"] = hours
    await answer_choice(update, f"{hours} hrs")
    await update.effective_message.reply_text(
        "📍 Where can it be picked up?",
        reply_markup=buttons([[("My saved location", "loc:saved")], [("A different spot", "loc:new")]]),
    )
    return PICKUP


async def chose_pickup(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    choice = update.callback_query.data.split(":")[1]
    if choice == "new":
        await answer_choice(update, "A different spot")
        await ask_location(update, "Where can it be picked up?")
        return PICKUP_NEW
    donor = context.user_data["donor"]
    context.user_data["draft"].update(lat=donor["lat"], lng=donor["lng"])
    await answer_choice(update, "My saved location")
    return await publish(update, context)


async def got_pickup_location(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    loc = update.effective_message.location
    context.user_data["draft"].update(lat=loc.latitude, lng=loc.longitude)
    await update.effective_message.reply_text("📍 Got it.", reply_markup=ReplyKeyboardRemove())
    return await publish(update, context)


async def publish(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    draft = context.user_data.pop("draft")
    donor = context.user_data.pop("donor")
    msg = update.effective_message
    await msg.reply_text("⏳ Posting your listing…")

    tg_file = await context.bot.get_file(draft["photo_file_id"])
    photo = bytes(await tg_file.download_as_bytearray())
    photo_url = await storage.upload_photo("donation-photos", photo)

    donation = await asyncio.to_thread(
        repo.create_donation,
        donor=donor,
        photo_url=photo_url,
        food_type=draft["food_type"],
        quantity=draft["quantity"],
        est_kg=draft["est_kg"],
        lat=draft["lat"],
        lng=draft["lng"],
        good_for_hours=draft["good_for_hours"],
        safety_checklist=draft.get("safety_checklist"),
    )
    radius_km = donation["search_radius_m"] / 1000
    await msg.reply_text(
        f"✅ *Live now!* {md(draft['food_type'])} ({md(draft['quantity'])})\n\n"
        f"Nearby community kitchens within {radius_km:g} km can see it. "
        f"If no one claims it soon, I'll widen the search automatically.\n"
        f"I'll message you as soon as it's claimed. ⏱ Good for {draft['good_for_hours']} hrs.",
        parse_mode="Markdown",
    )
    return END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    await update.effective_message.reply_text(
        "Cancelled. Send a photo whenever you have food to share.", reply_markup=ReplyKeyboardRemove()
    )
    return END


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    log.exception("bot handler failed", exc_info=context.error)
    if isinstance(update, Update) and update.effective_message:
        await update.effective_message.reply_text("😕 Something went wrong on our side. Please try again.")


# ---------------------------------------------------------------------------

def build_application(token: str) -> Application:
    app = Application.builder().token(token).build()
    text = filters.TEXT & ~filters.COMMAND
    fallbacks = [CommandHandler("cancel", cancel)]

    onboarding = ConversationHandler(
        entry_points=[CommandHandler("start", start), CommandHandler("profile", ask_role)],
        states={
            ROLE: [CallbackQueryHandler(chose_role, pattern=r"^role:")],
            NAME: [MessageHandler(text, got_name)],
            DONOR_TYPE: [CallbackQueryHandler(chose_type, pattern=r"^type:")],
            LOCATION: [MessageHandler(filters.LOCATION, got_location), MessageHandler(text, location_expected)],
            PLEDGE: [CallbackQueryHandler(pledged, pattern=r"^pledge:")],
        },
        fallbacks=fallbacks,
        allow_reentry=True,
        name="onboarding",
    )

    posting = ConversationHandler(
        entry_points=[MessageHandler(filters.PHOTO, got_photo)],
        states={
            FOOD: [MessageHandler(text, got_food)],
            QUANTITY: [MessageHandler(text, got_quantity)],
            WEIGHT: [CallbackQueryHandler(chose_weight, pattern=r"^kg:")],
            HOURS: [CallbackQueryHandler(chose_hours, pattern=r"^hrs:")],
            PICKUP: [CallbackQueryHandler(chose_pickup, pattern=r"^loc:")],
            PICKUP_NEW: [MessageHandler(filters.LOCATION, got_pickup_location), MessageHandler(text, location_expected)],
        },
        fallbacks=fallbacks,
        allow_reentry=True,  # a new photo restarts the draft
        name="posting",
    )

    app.add_handler(onboarding)
    app.add_handler(posting)
    app.add_error_handler(on_error)
    return app
