"""Telegram donor flows: onboarding (/start) and posting (send a photo).

Each handler is `async (update, context) -> next_state`, so tests can drive the
conversations with mock updates without talking to Telegram.
"""
import asyncio
import logging
import re
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

from app.services import ai_intake, repo, storage

log = logging.getLogger(__name__)

# Conversations are tracked per chat on purpose (buttons belong to the current step)
warnings.filterwarnings("ignore", message=r"If 'per_message=False'")

# Onboarding states
ROLE, NAME, DONOR_TYPE, LOCATION, PLEDGE = range(5)
# Posting states
FOOD, QUANTITY, WEIGHT, HOURS, PICKUP, PICKUP_NEW, SAFETY, AI_CONFIRM, LISTING_TYPE, PRICE = range(10, 20)

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

# Asked before every listing goes live. Any "No" blocks the post with the matching reason.
SAFETY_CHECKLIST = [
    (
        "hygienic",
        "🧼 Was it prepared and handled hygienically (clean hands and utensils, kept covered)?",
        "food that may not have been handled hygienically",
    ),
    (
        "safe_temperature",
        "🌡️ Has it been kept at a safe temperature (refrigerated, or kept hot / freshly cooked)?",
        "food that hasn't been kept at a safe temperature",
    ),
    (
        "contents_known",
        "🥜 Do you know what's in it, including common allergens (nuts, shellfish, eggs, milk)?",
        "food with unknown contents, because recipients may have allergies",
    ),
]


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
    context.user_data.pop("editing", None)  # a fresh onboarding, not a profile edit
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


async def edit_profile(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """/profile: walk the same steps, but show current values with Keep buttons and skip the pledge."""
    donor = await asyncio.to_thread(repo.get_donor_by_chat, update.effective_chat.id)
    if not donor:
        return await ask_role(update, context)
    context.user_data["editing"] = donor
    await update.effective_message.reply_text(
        "✏️ *Update your profile*\n\n"
        f"Name: {md(donor['name'])}\n"
        f"Type: {donor['type'].capitalize()}\n\n"
        "What name should recipients see? Type a new one or keep it:",
        parse_mode="Markdown",
        reply_markup=buttons([[(f"Keep \"{donor['name'][:40]}\"", "keep:name")]]),
    )
    return NAME


async def got_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    editing = context.user_data.get("editing")
    if update.callback_query:  # Keep current name
        name = editing["name"]
        await answer_choice(update, "Kept")
    else:
        name = update.effective_message.text.strip()[:80]
    context.user_data["profile"] = {"name": name}
    current = editing["type"] if editing else None
    label = lambda t, text: f"{text} (current)" if t == current else text  # noqa: E731
    await update.effective_message.reply_text(
        "Are you a business or a household?",
        reply_markup=buttons([[(label("business", "🏪 Business"), "type:business"),
                               (label("household", "🏠 Household"), "type:household")]]),
    )
    return DONOR_TYPE


async def chose_type(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    type_ = update.callback_query.data.split(":")[1]
    context.user_data["profile"]["type"] = type_
    await answer_choice(update, type_.capitalize())
    await ask_location(
        update, "Where is your usual pickup spot? (You can use a different spot for each donation later.)"
    )
    if context.user_data.get("editing"):
        await update.effective_message.reply_text(
            "…or keep the one you have:", reply_markup=buttons([[("📍 Keep my saved pickup spot", "keep:loc")]])
        )
    return LOCATION


async def got_location(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    editing = context.user_data.get("editing")
    if update.callback_query:  # Keep saved spot (profile edit only)
        await answer_choice(update, "Kept")
        context.user_data["profile"].update(lat=editing["lat"], lng=editing["lng"])
    else:
        loc = update.effective_message.location
        context.user_data["profile"].update(lat=loc.latitude, lng=loc.longitude)
    await update.effective_message.reply_text("📍 Got it.", reply_markup=ReplyKeyboardRemove())

    if editing:  # already pledged: save straight away
        p = context.user_data.pop("profile")
        context.user_data.pop("editing")
        await asyncio.to_thread(repo.create_donor, update.effective_chat.id, p["name"], p["type"], p["lat"], p["lng"])
        await update.effective_message.reply_text(
            f"✅ *Profile updated:* {md(p['name'])} · {p['type'].capitalize()}\n\nSend a photo whenever you have food to share.",
            parse_mode="Markdown",
        )
        return END

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

    tg_file = await context.bot.get_file(msg.photo[-1].file_id)  # largest size
    context.user_data["draft"] = {"photo": bytes(await tg_file.download_as_bytearray())}
    context.user_data["donor"] = donor
    caption = (msg.caption or "").strip()

    listing = None
    if ai_intake.enabled():
        await msg.reply_text("🔍 Looking at your photo…")
        listing = await ai_intake.parse_food_photo(context.user_data["draft"]["photo"], caption or None)
    if listing and listing.is_food:
        context.user_data["draft"]["ai"] = listing.model_dump()
        await msg.reply_text(
            ai_summary(listing),
            parse_mode="Markdown",
            reply_markup=buttons([[("✅ Looks right", "ai:ok"), ("✏️ Fix details", "ai:edit")]]),
        )
        return AI_CONFIRM
    if listing and not listing.is_food:
        await msg.reply_text("🤔 That doesn't look like food to me. If it is, let's add the details by hand.")
    return await ask_manual(update, context, caption)


def ai_summary(listing: "ai_intake.FoodListing") -> str:
    lines = [
        "🤖 *Here's what I see:*",
        f"🍱 {md(listing.food_type)}",
        f"📦 {md(listing.quantity)} (~{listing.est_kg:g} kg)",
        f"⏱ Good for about {listing.good_for_hours} hrs",
    ]
    if listing.allergens:
        lines.append(f"⚠️ May contain: {md(', '.join(listing.allergens))}")
    lines.append("")
    lines.append("Is this right?" if listing.confidence != "low" else "I'm not fully sure, so please check. Is this right?")
    return "\n".join(lines)


async def chose_ai(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    draft = context.user_data["draft"]
    ai = draft.pop("ai")
    if update.callback_query.data == "ai:edit":
        await answer_choice(update, "Fix details")
        return await ask_manual(update, context, caption="")
    await answer_choice(update, "Looks right")
    draft.update(
        food_type=ai["food_type"],
        quantity=ai["quantity"],
        est_kg=ai["est_kg"],
        good_for_hours=ai["good_for_hours"],
        allergens=ai["allergens"],
        suggested_price=ai["suggested_price_php"],
        ai_assisted=True,
    )
    return await after_details(update, context)


async def ask_manual(update: Update, context: ContextTypes.DEFAULT_TYPE, caption: str) -> int:
    msg = update.effective_message
    if caption:
        context.user_data["draft"]["food_type"] = caption[:120]
        await msg.reply_text(f"📸 Thanks! Food: *{md(caption[:120])}*", parse_mode="Markdown")
        return await ask_quantity(update, context)

    await msg.reply_text("What food is it? (e.g. \"Pandesal\", \"Chicken adobo with rice\")")
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
    return await after_details(update, context)


async def after_details(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Businesses may sell at a discount; households go straight to pickup (free donation)."""
    if context.user_data["donor"]["type"] != "business":
        return await ask_pickup(update, context)
    await update.effective_message.reply_text(
        "How do you want to share it?",
        reply_markup=buttons([[("🎁 Donate free", "lt:donation"), ("🏷️ Sell at a discount", "lt:sale")]]),
    )
    return LISTING_TYPE


async def chose_listing_type(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.callback_query.data == "lt:donation":
        await answer_choice(update, "Donate free")
        return await ask_pickup(update, context)
    await answer_choice(update, "Sell at a discount")
    minutes = await asyncio.to_thread(repo.sale_window_minutes)
    text = (
        "🏷️ What's your discounted price for the whole lot, in pesos?\n"
        "Buyers reserve it here and pay you in person at pickup (cash or GCash).\n\n"
        f"The price drops over the next {minutes:g} min. If it's still unsold then, it becomes a free donation "
        "so nothing goes to waste."
    )
    suggested = context.user_data["draft"].get("suggested_price")
    if suggested:
        await update.effective_message.reply_text(
            f"{text}\n\nTap the suggestion or type your own price:",
            reply_markup=buttons([[(f"₱{suggested:g} (suggested)", f"price:{suggested:g}")]]),
        )
    else:
        await update.effective_message.reply_text(f"{text}\n\nType a price, e.g. 120")
    return PRICE


def parse_price(text: str) -> float | None:
    """'₱1,200', 'P85.50', '120 pesos' -> whole pesos; None if missing or out of range."""
    m = re.search(r"\d+(?:\.\d+)?", text.replace(",", ""))
    if not m:
        return None
    price = round(float(m.group()))
    return price if 1 <= price <= 100_000 else None


async def got_price(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int | None:
    if update.callback_query:
        price = float(update.callback_query.data.split(":")[1])
        await answer_choice(update, f"₱{price:g}")
    else:
        price = parse_price(update.effective_message.text)
        if price is None:
            await update.effective_message.reply_text("Please type the price as a number of pesos, e.g. 120")
            return None
    context.user_data["draft"].update(listing_type="sale", price=price)
    return await ask_pickup(update, context)


async def ask_pickup(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
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
    return await ask_safety(update, context, 0)


async def got_pickup_location(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    loc = update.effective_message.location
    context.user_data["draft"].update(lat=loc.latitude, lng=loc.longitude)
    await update.effective_message.reply_text("📍 Got it.", reply_markup=ReplyKeyboardRemove())
    return await ask_safety(update, context, 0)


async def ask_safety(update: Update, context: ContextTypes.DEFAULT_TYPE, index: int) -> int:
    if index == 0:
        context.user_data["draft"]["safety_checklist"] = {}
        await update.effective_message.reply_text("Last step: a quick safety check (3 taps) ✅")
    _, question, _ = SAFETY_CHECKLIST[index]
    await update.effective_message.reply_text(
        f"{index + 1}/{len(SAFETY_CHECKLIST)} {question}",
        reply_markup=buttons([[("Yes", f"safe:{index}:yes"), ("No", f"safe:{index}:no")]]),
    )
    return SAFETY


async def answered_safety(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int | None:
    _, index, answer = update.callback_query.data.split(":")
    index = int(index)
    checklist = context.user_data["draft"]["safety_checklist"]
    if index != len(checklist):  # an old button tapped out of order
        await update.callback_query.answer("Please answer the latest question.")
        return None

    key, _, block_reason = SAFETY_CHECKLIST[index]
    await answer_choice(update, answer.capitalize())

    if answer == "no":
        context.user_data.pop("draft", None)
        context.user_data.pop("donor", None)
        await update.effective_message.reply_text(
            "Thank you for being honest 💚\n\n"
            f"To keep recipients safe, we can't list {block_reason}. "
            "This listing was not posted.\n\n"
            "Send a new photo anytime you have food that passes the check."
        )
        return END

    checklist[key] = True
    if index + 1 < len(SAFETY_CHECKLIST):
        return await ask_safety(update, context, index + 1)
    return await publish(update, context)


async def publish(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    draft = context.user_data.pop("draft")
    donor = context.user_data.pop("donor")
    msg = update.effective_message
    await msg.reply_text("⏳ Posting your listing…")

    photo_url = await storage.upload_photo("donation-photos", draft["photo"])

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
        allergens=draft.get("allergens"),
        ai_assisted=draft.get("ai_assisted", False),
        suggested_price=draft.get("suggested_price"),
        listing_type=draft.get("listing_type", "donation"),
        price=draft.get("price"),
    )
    radius_km = donation["search_radius_m"] / 1000
    if donation["listing_type"] == "sale":
        details = (
            f"🏷️ For sale at ₱{draft['price']:g}. Buyers within {radius_km:g} km can reserve it and pay you at pickup. "
            "If it's still unsold when the price timer ends, it becomes a free donation.\n"
            "I'll message you as soon as it's reserved."
        )
    else:
        details = (
            f"Nearby community kitchens within {radius_km:g} km can see it. "
            "If no one claims it soon, I'll widen the search automatically.\n"
            "I'll message you as soon as it's claimed."
        )
    await msg.reply_text(
        f"✅ *Live now!* {md(draft['food_type'])} ({md(draft['quantity'])})\n\n"
        f"{details} ⏱ Good for {draft['good_for_hours']} hrs.",
        parse_mode="Markdown",
    )
    return END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    await update.effective_message.reply_text(
        "Cancelled. Send a photo whenever you have food to share.", reply_markup=ReplyKeyboardRemove()
    )
    return END


# ---------------------------------------------------------------------------
# Catch-alls: conversation state lives in memory, so after a restart (every deploy) a donor's
# half-finished post is forgotten. Whatever they tap or type next must still get an answer.
# ---------------------------------------------------------------------------

async def stale_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    try:
        await query.edit_message_reply_markup(reply_markup=None)  # remove the dead buttons
    except Exception:  # noqa: BLE001 - message too old to edit, etc.
        pass
    await update.effective_message.reply_text(
        "⏱ That step expired (the bot was restarted or it's been a while).\n\n"
        "Please send the photo again to start over, or /start."
    )


async def unexpected_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(
        "To share food, just send a photo of it 📸\n/profile to update your details · /cancel to stop a post"
    )


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    log.exception("bot handler failed", exc_info=context.error)
    if isinstance(update, Update) and update.effective_message:
        await update.effective_message.reply_text(
            "😕 Something went wrong on our side (probably a connection hiccup).\n\n"
            "If you were posting food, just send the photo again to start over. "
            "Otherwise, send /start."
        )


# ---------------------------------------------------------------------------

def build_application(token: str, request=None) -> Application:
    """`request` lets tests swap in a fake Telegram HTTP layer."""
    builder = Application.builder().token(token)
    if request is not None:
        builder = builder.request(request).get_updates_request(request)
    app = builder.build()
    text = filters.TEXT & ~filters.COMMAND
    fallbacks = [CommandHandler("cancel", cancel)]

    onboarding = ConversationHandler(
        entry_points=[CommandHandler("start", start), CommandHandler("profile", edit_profile)],
        states={
            ROLE: [CallbackQueryHandler(chose_role, pattern=r"^role:")],
            NAME: [MessageHandler(text, got_name), CallbackQueryHandler(got_name, pattern=r"^keep:name$")],
            DONOR_TYPE: [CallbackQueryHandler(chose_type, pattern=r"^type:")],
            LOCATION: [
                MessageHandler(filters.LOCATION, got_location),
                CallbackQueryHandler(got_location, pattern=r"^keep:loc$"),
                MessageHandler(text, location_expected),
            ],
            PLEDGE: [CallbackQueryHandler(pledged, pattern=r"^pledge:")],
        },
        fallbacks=fallbacks,
        allow_reentry=True,
        name="onboarding",
    )

    posting = ConversationHandler(
        entry_points=[MessageHandler(filters.PHOTO, got_photo)],
        states={
            AI_CONFIRM: [CallbackQueryHandler(chose_ai, pattern=r"^ai:")],
            LISTING_TYPE: [CallbackQueryHandler(chose_listing_type, pattern=r"^lt:")],
            PRICE: [CallbackQueryHandler(got_price, pattern=r"^price:"), MessageHandler(text, got_price)],
            FOOD: [MessageHandler(text, got_food)],
            QUANTITY: [MessageHandler(text, got_quantity)],
            WEIGHT: [CallbackQueryHandler(chose_weight, pattern=r"^kg:")],
            HOURS: [CallbackQueryHandler(chose_hours, pattern=r"^hrs:")],
            PICKUP: [CallbackQueryHandler(chose_pickup, pattern=r"^loc:")],
            PICKUP_NEW: [MessageHandler(filters.LOCATION, got_pickup_location), MessageHandler(text, location_expected)],
            SAFETY: [CallbackQueryHandler(answered_safety, pattern=r"^safe:")],
        },
        fallbacks=fallbacks,
        allow_reentry=True,  # a new photo restarts the draft
        name="posting",
    )

    app.add_handler(onboarding)
    app.add_handler(posting)
    # Same group, registered last: only reached when no conversation handled the update
    app.add_handler(CommandHandler("cancel", cancel))
    app.add_handler(CallbackQueryHandler(stale_button))
    app.add_handler(MessageHandler(text, unexpected_text))
    app.add_error_handler(on_error)
    return app
