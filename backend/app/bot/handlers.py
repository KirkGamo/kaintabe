"""Telegram donor flows: onboarding (/start) and posting (send a photo).

Each handler is `async (update, context) -> next_state`, so tests can drive the
conversations with mock updates without talking to Telegram.
"""
import asyncio
import logging
import re
import warnings
from datetime import datetime, timezone

import httpx
import psycopg
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    Update,
    WebAppInfo,
)
from telegram.error import NetworkError
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from app.config import settings
from app.services import ai_intake, notify, offer_messages, repo, storage
from app.services import telegram as tg_out  # outgoing messages to other chats (e.g. the donor)
from app.services.notify import md

log = logging.getLogger(__name__)

# Conversations are tracked per chat on purpose (buttons belong to the current step)
warnings.filterwarnings("ignore", message=r"If 'per_message=False'")

# Onboarding states
ROLE, NAME, DONOR_TYPE, LOCATION, PLEDGE, IND_LOCATION, IND_NAME = range(7)
# Partner-org sign-up states
ORG_PICK, ORG_NAME, ORG_KIND, ORG_LOCATION, ORG_RADIUS, ORG_HOURS, ORG_CAPACITY = range(30, 37)

ORG_KINDS = [("🍲 Community kitchen", "community_kitchen"), ("🏠 Shelter", "shelter"),
             ("🏦 Food bank", "food_bank"), ("🧺 Pantry", "pantry")]
ORG_RADII_KM = [3, 5, 8]
# Posting states
FOOD, QUANTITY, WEIGHT, HOURS, PICKUP, PICKUP_NEW, SAFETY, AI_CONFIRM, LISTING_TYPE, PRICE, PHOTO_PURPOSE = range(10, 21)

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


def buttons(rows: list[list[tuple[str, str]]], with_map: bool = False) -> InlineKeyboardMarkup:
    keyboard = [[InlineKeyboardButton(t, callback_data=d) for t, d in row] for row in rows]
    map_button = open_map_button() if with_map else None
    if map_button:
        keyboard.append([map_button])
    return InlineKeyboardMarkup(keyboard)


def open_map_button() -> InlineKeyboardButton | None:
    """Opens the live map inside Telegram (Mini App). None without an https web URL."""
    url = settings.map_url
    return InlineKeyboardButton("🗺️ Open map", web_app=WebAppInfo(url=url)) if url else None


def map_only() -> InlineKeyboardMarkup | None:
    button = open_map_button()
    return InlineKeyboardMarkup([[button]]) if button else None


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

def rescued_line(label: str, stats: dict) -> str | None:
    """'💚 Your impact: 5 pickups · 12 kg ≈ 30 meals', or None before the first pickup."""
    n, kg = stats["pickups"], stats["kg"]
    if not n:
        return None
    line = f"💚 {label}: {n} pickup{'' if n == 1 else 's'}"
    if kg:
        meals = max(1, round(kg / notify.KG_PER_MEAL))
        line += f" · {kg:g} kg ≈ {meals} meal{'' if meals == 1 else 's'}"
    return line


def lines(*parts: str | None) -> str:
    """Join message lines, leaving out the ones with nothing to report."""
    return "\n".join(p for p in parts if p)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    chat_id, bot = update.effective_chat.id, context.bot.username
    org, donor, person = await asyncio.gather(
        asyncio.to_thread(repo.get_org, chat_id, bot),
        asyncio.to_thread(repo.get_donor_by_chat, chat_id),
        asyncio.to_thread(repo.get_individual, chat_id, bot),
    )
    if org:
        await reply_org_welcome(update, org, returning=True, is_donor=bool(donor))
        return END
    on_list = bool(person and person["active"])
    if donor:
        stats, live = await asyncio.gather(
            asyncio.to_thread(repo.rescued_stats, donor_id=donor["id"]),
            asyncio.to_thread(repo.my_active_listings, donor["id"]),
        )
        body = lines(
            rescued_line("Your impact", stats),
            f"📦 Live now: {len(live)} listing{'' if len(live) == 1 else 's'} "
            "(/mylistings to see or take them down)" if live else None,
        )
        await update.effective_message.reply_text(
            f"Welcome back, {md(donor['name'])}! 👋\n\n"
            + (f"{body}\n\n" if body else "")
            + "📸 Have surplus? Just *send a photo* of it.\n/profile to update your details."
            + ("\n\n💚 You're also on the flash-offer list (/stop to leave)." if on_list else ""),
            parse_mode="Markdown",
            # donors can also receive flash offers; the button re-enters the recipient branch
            reply_markup=map_only() if on_list
            else buttons([[("🙋 Get free-food offers near me", "role:recipient")]], with_map=True),
        )
        return END if on_list else ROLE
    if person:
        stats = await asyncio.to_thread(repo.rescued_stats, recipient_id=person["id"])
        n = stats["pickups"]
        so_far = f" {n} pickup{'' if n == 1 else 's'} so far." if n else ""
        if on_list:
            text = ("You're on the flash-offer list. I'll message you when free food near you would otherwise "
                    f"go to waste.{so_far}\n/stop to pause offers.")
            markup = map_only()
        else:
            text = f"Your flash offers are paused.{so_far} Turn them back on anytime:"
            markup = buttons([[("🙋 Turn offers back on", "role:recipient")]], with_map=True)
        await update.effective_message.reply_text(
            f"Welcome back, {md(person['name'])}! 💚\n\n{text}", parse_mode="Markdown", reply_markup=markup
        )
        return END
    return await ask_role(update, context)


async def ask_role(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.pop("editing", None)  # a fresh onboarding, not a profile edit
    try:
        s = await asyncio.to_thread(repo.community_stats)
    except Exception:  # the numbers are a nice-to-have; never block sign-up on them
        log.warning("community stats unavailable", exc_info=True)
        s = {"kg": 0, "live": 0}
    live = s["live"]
    numbers = lines(
        f"💚 So far: {s['kg']:g} kg rescued · ≈ {s['meals']} meals · {s['co2e_kg']:g} kg CO₂e avoided"
        if s["kg"] else None,
        f"📍 Right now: {live} listing{'' if live == 1 else 's'} on the map" if live else None,
    )
    await update.effective_message.reply_text(
        "🍱 *KainTabe: food rescue for Iloilo*\n\n"
        "Surplus food from restaurants, bakeries and homes reaches community kitchens and neighbors "
        "before it spoils.\n\n"
        + (f"{numbers}\n\n" if numbers else "")
        + "*How it works*\n"
        "1️⃣ A donor sends a photo of surplus food\n"
        "2️⃣ The nearest kitchen gets an alert and claims it\n"
        "3️⃣ Pickup is confirmed with a photo\n\n"
        "What brings you here?",
        parse_mode="Markdown",
        reply_markup=buttons(
            [[("🍱 I have food to share", "role:donor")],
             [("🏢 We're a community kitchen / org", "role:org")],
             [("🙋 I need food", "role:recipient")]],
            with_map=True,
        ),
    )
    return ROLE


async def chose_role(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    role = update.callback_query.data.split(":")[1]
    if role == "org":
        return await org_start(update, context)
    if role == "recipient":
        await answer_choice(update, "I need food")
        person = await asyncio.to_thread(repo.get_individual, update.effective_chat.id, context.bot.username)
        if person and person["active"]:
            await update.effective_message.reply_text(
                "💚 You're already on the list for flash offers near you. Send /stop to leave it."
            )
            return END
        await update.effective_message.reply_text(
            "💚 *Flash offers*\n\n"
            "When food near you is about to go to waste and no community kitchen can take it in time, "
            "I'll message you. It's free, and the first person to tap gets it.",
            parse_mode="Markdown",
        )
        tg_name = telegram_first_name(update)
        await update.effective_message.reply_text(
            "What name should the donor see when you come to pick up?",
            reply_markup=buttons([[(f'Use "{tg_name}"', "indname:tg")]]) if tg_name else None,
        )
        return IND_NAME
    await answer_choice(update, "I have food to share")
    await update.effective_message.reply_text(
        "Great! Let's set up your donor profile (takes 30 seconds).\n\n"
        "What name should recipients see? (e.g. your business or \"Household in Jaro\")"
    )
    return NAME


# ---------------------------------------------------------------------------
# Partner organizations: link a seeded org or register a new one (self-declared)
# ---------------------------------------------------------------------------

async def reply_org_welcome(update: Update, org: dict, returning: bool = False, is_donor: bool | None = None) -> None:
    status = ("🕓 Pending review (self-declared; you can already claim food)"
              if org["review_status"] == "pending_review" else "✅ Verified partner")
    head = f"Welcome back, *{md(org['name'])}*! 🏢" if returning else f"✅ *You're set up as {md(org['name'])}*"
    if is_donor is None:
        is_donor = bool(await asyncio.to_thread(repo.get_donor_by_chat, update.effective_chat.id))
    km = f"{org['service_radius_m'] / 1000:g} km"
    now = ""
    if returning:  # what's waiting for them right now
        near, pending, stats = await asyncio.gather(
            asyncio.to_thread(repo.listings_in_range, org["id"]),
            asyncio.to_thread(repo.pending_pickups, [org["id"]]),
            asyncio.to_thread(repo.rescued_stats, recipient_id=org["id"]),
        )
        now = lines(
            f"🍲 Near you now: {len(near)} listing{'' if len(near) == 1 else 's'} within {km}" if near else None,
            f"🚚 Waiting for your pickup: {md(pending[0]['food_type'])}"
            + (f" and {len(pending) - 1} more" if len(pending) > 1 else "")
            + " (send a photo when you have it)" if pending else None,
            rescued_line("Rescued by you so far", stats),
        )
    await update.effective_message.reply_text(
        f"{head}\n\nStatus: {status}\n\n"
        + (f"{now}\n\n" if now else "")
        + f"I'll alert you when surplus food appears within *{km}*, "
        "and you can claim it in one tap. Open the map anytime with the 🗺️ button."
        + ("\n\n🍱 You're also a donor: send a photo anytime to share food." if is_donor else ""),
        parse_mode="Markdown",
        # an org's staff may have their own surplus too; don't make donating a dead end
        reply_markup=map_only() if is_donor else buttons([[("🍱 I also have food to share", "role:donor")]], with_map=True),
    )


async def org_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await answer_choice(update, "We're an organization")
    orgs = await asyncio.to_thread(repo.unlinked_orgs)
    rows = [[(f"🔗 {o['name']}", f"orglink:{o['id']}")] for o in orgs]
    rows.append([("➕ Register a new organization", "orglink:new")])
    await update.effective_message.reply_text(
        "🏢 *Partner organizations* get an alert when surplus food appears nearby and claim it in one tap.\n\n"
        + ("Is your organization already listed? Link it, or register a new one:" if orgs
           else "Let's register your organization:"),
        parse_mode="Markdown",
        reply_markup=buttons(rows),
    )
    return ORG_PICK


async def org_picked(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    choice = update.callback_query.data.split(":", 1)[1]
    if choice == "new":
        await answer_choice(update, "Register a new organization")
        context.user_data["org"] = {}
        await update.effective_message.reply_text("What's the organization's name?")
        return ORG_NAME
    try:
        org = await asyncio.to_thread(repo.link_org, choice, update.effective_chat.id, context.bot.username)
    except repo.NotAvailable:
        await update.callback_query.answer("Someone already linked that organization.", show_alert=True)
        return None  # stay: they can pick another or register new
    await answer_choice(update, f"Linked: {org['name']}")
    await reply_org_welcome(update, org)
    return END


async def got_org_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["org"] = {"name": update.effective_message.text.strip()[:80]}
    await update.effective_message.reply_text(
        "What kind of organization is it?",
        reply_markup=buttons([[(label, f"okind:{kind}")] for label, kind in ORG_KINDS]),
    )
    return ORG_KIND


async def chose_org_kind(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    kind = update.callback_query.data.split(":", 1)[1]
    context.user_data["org"]["org_kind"] = kind
    await answer_choice(update, dict((k, label) for label, k in ORG_KINDS)[kind])
    await ask_location(update, "Where do you receive or pick up food from? (Your kitchen or pantry.)")
    return ORG_LOCATION


async def got_org_location(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    loc = update.effective_message.location
    context.user_data["org"].update(lat=loc.latitude, lng=loc.longitude)
    await update.effective_message.reply_text("📍 Got it.", reply_markup=ReplyKeyboardRemove())
    await update.effective_message.reply_text(
        "How far can you travel to pick food up?",
        reply_markup=buttons([[(f"{km} km", f"orad:{km}") for km in ORG_RADII_KM]]),
    )
    return ORG_RADIUS


async def chose_org_radius(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    km = int(update.callback_query.data.split(":", 1)[1])
    context.user_data["org"]["service_radius_m"] = km * 1000
    await answer_choice(update, f"{km} km")
    await update.effective_message.reply_text("What are your operating hours? (e.g. \"7:00–20:00\" or \"24 hours\")")
    return ORG_HOURS


async def got_org_hours(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["org"]["hours"] = update.effective_message.text.strip()[:60]
    await update.effective_message.reply_text("Roughly how many meals can you take in a day? (e.g. \"60 meals/day\")")
    return ORG_CAPACITY


async def got_org_capacity(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    o = context.user_data["org"]  # keep the answers until the save succeeds, so a retry works
    org = await asyncio.to_thread(
        repo.create_org, update.effective_chat.id, context.bot.username,
        name=o["name"], org_kind=o["org_kind"], lat=o["lat"], lng=o["lng"],
        service_radius_m=o["service_radius_m"], hours=o["hours"],
        capacity=update.effective_message.text.strip()[:60],
    )
    context.user_data.pop("org", None)
    await reply_org_welcome(update, org)
    return END


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


def telegram_first_name(update: Update) -> str | None:
    user = getattr(update, "effective_user", None)
    name = (getattr(user, "first_name", None) or "").strip()[:40]
    return name or None


async def got_individual_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.callback_query:  # "Use <Telegram name>"
        name = telegram_first_name(update) or "Neighbor"
        await answer_choice(update, name)
    else:
        name = update.effective_message.text.strip()[:40]
    context.user_data["ind_name"] = name
    await ask_location(update, "Where should offers be near? (Within about 3 km of this spot.)")
    return IND_LOCATION


async def got_individual_location(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    loc = update.effective_message.location
    # the name step normally sets this; a flow started before it existed falls back to Telegram's name
    name = context.user_data.pop("ind_name", None) or telegram_first_name(update) or "Neighbor"
    await asyncio.to_thread(
        repo.upsert_individual, update.effective_chat.id, name, loc.latitude, loc.longitude, context.bot.username
    )
    await update.effective_message.reply_text("📍 Got it.", reply_markup=ReplyKeyboardRemove())
    await update.effective_message.reply_text(
        "✅ *You're on the list!*\n\n"
        "I'll message you when there's free food within about 3 km that would otherwise go to waste. "
        "Tap fast: it's first come, first served.\n\n"
        "Send /stop anytime to stop the offers.",
        parse_mode="Markdown",
    )
    return END


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
        reply_markup=map_only(),
    )
    return END


# ---------------------------------------------------------------------------
# Posting a donation
# ---------------------------------------------------------------------------

async def got_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """A photo is new food to share, or an individual confirming a flash-offer pickup."""
    msg = update.effective_message
    chat_id = update.effective_chat.id
    donor = await asyncio.to_thread(repo.get_donor_by_chat, chat_id)
    # a claim made by this chat as an individual (flash offer) or as a partner org, awaiting its photo
    pending = await asyncio.to_thread(repo.pending_pickup_for_chat, chat_id, context.bot.username)
    if not donor and not pending:
        await msg.reply_text(
            "📸 To share food, set up a donor profile first (takes 30 seconds), then send the photo again.",
            reply_markup=buttons([[("🍱 Set up a donor profile", "role:donor")]]),
        )
        return END

    # Keep only Telegram's file id (JSON-safe, survives restarts); download the bytes when needed
    context.user_data["photo_file_id"] = msg.photo[-1].file_id  # largest size
    context.user_data["caption"] = (msg.caption or "").strip()
    context.user_data["donor"] = donor

    if pending:
        context.user_data["pending_pickup"] = pending
        if not donor:
            return await confirm_pickup_by_photo(update, context)
        await msg.reply_text(
            "Is this photo…",
            reply_markup=buttons([[(f"✅ My pickup of {pending['food_type'][:30]}", "purpose:pickup")],
                                  [("📸 New food to share", "purpose:share")]]),
        )
        return PHOTO_PURPOSE
    return await start_listing(update, context)


async def chose_photo_purpose(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.callback_query.data == "purpose:pickup":
        await answer_choice(update, "Pickup confirmation")
        return await confirm_pickup_by_photo(update, context)
    await answer_choice(update, "New food to share")
    context.user_data.pop("pending_pickup", None)
    return await start_listing(update, context)


async def confirm_pickup_by_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    pending = context.user_data.pop("pending_pickup")
    photo = await download_photo(context, context.user_data.pop("photo_file_id"))
    for key in ("caption", "donor"):
        context.user_data.pop(key, None)
    photo_url = await storage.upload_photo("pickup-photos", photo)
    try:
        done = await asyncio.to_thread(repo.confirm_pickup, str(pending["id"]), photo_url)
    except repo.NotAvailable:
        await update.effective_message.reply_text("This pickup was already confirmed. Salamat! 💚")
        return END
    await update.effective_message.reply_text(
        f"🙏 Pickup confirmed: {md(done['food_type'])}. Salamat for making sure it didn't go to waste! 💚",
        parse_mode="Markdown",
    )
    await tg_out.send_photo(done["donor_chat_id"], photo, notify.picked_up_text(done))
    return END


async def download_photo(context: ContextTypes.DEFAULT_TYPE, file_id: str) -> bytes:
    tg_file = await context.bot.get_file(file_id)
    return bytes(await tg_file.download_as_bytearray())


async def start_listing(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    msg = update.effective_message
    context.user_data["draft"] = {"photo_file_id": context.user_data.pop("photo_file_id")}
    caption = context.user_data.pop("caption", "")

    listing = None
    if ai_intake.enabled():
        await msg.reply_text("🔍 Looking at your photo…")
        photo = await download_photo(context, context.user_data["draft"]["photo_file_id"])
        listing = await ai_intake.parse_food_photo(photo, caption or None)
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

    photo_url = await storage.upload_photo("donation-photos", await download_photo(context, draft["photo_file_id"]))

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
            "I'll message you as soon as it's reserved. Sold it elsewhere? /mylistings"
        )
    else:
        details = (
            f"Nearby community kitchens within {radius_km:g} km can see it. "
            "If no one claims it soon, I'll widen the search automatically.\n"
            "I'll message you as soon as it's claimed. Already gone? /mylistings"
        )
    await msg.reply_text(
        f"✅ *Live now!* {md(draft['food_type'])} ({md(draft['quantity'])})\n\n"
        f"{details} ⏱ Good for {draft['good_for_hours']} hrs.",
        parse_mode="Markdown",
        reply_markup=map_only(),
    )
    return END


DEMO_ROLES = {
    "donor": ("donor", "Send a photo to share food."),
    "org": ("partner org", "Food posted within your radius sends you an alert. 🗺️ Map shows your pickups."),
    "individual": ("individual", "Flash offers arrive when food near you isn't taken by any kitchen."),
}


async def demo_switch(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Try every side of KainTabe with one Telegram account: play one role at a time.

    /demo donor|org|individual  keep only that role (others parked, restorable)
    /demo fresh                 park every role: /start then behaves like a brand-new user
    /demo all                   bring every parked role back
    Open to everyone: it only ever parks or restores the sender's own profiles.
    """
    chat_id = update.effective_chat.id
    context.user_data.clear()  # drop any half-finished draft; this also ends the current conversation
    bot = context.bot.username
    arg = (context.args[0].lower() if context.args else "")

    if arg in DEMO_ROLES:
        await asyncio.to_thread(repo.park_roles, chat_id, bot, [k for k in repo.ROLE_KINDS if k != arg])
        row = await asyncio.to_thread(repo.restore_role, chat_id, bot, arg)
        label, hint = DEMO_ROLES[arg]
        if row and arg == "individual":
            await asyncio.to_thread(repo.set_individual_active, chat_id, bot, True)
        text = (f"🎭 *Demo:* you're now only the {label} *{md(row['name'])}*.\n\n{hint}" if row else
                f"🎭 *Demo:* other roles set aside. You have no {label} profile yet: send /start to register one.")
    elif arg == "fresh":
        await asyncio.to_thread(repo.park_roles, chat_id, bot, repo.ROLE_KINDS)
        text = "🎭 *Demo:* every role set aside. You're a brand-new user now: send /start."
    elif arg == "all":
        for kind in repo.ROLE_KINDS:
            await asyncio.to_thread(repo.restore_role, chat_id, bot, kind)
        text = "🎭 *Demo:* all your roles are back."
    else:
        text = ("🎭 *Try every role*\n\n"
                "See KainTabe from each side with this one account:\n"
                "/demo donor · /demo org · /demo individual: play only that role\n"
                "/demo fresh: start over as a new user, then /start to sign up as any role\n"
                "/demo all: bring all your roles back\n\n"
                "Nothing is deleted: roles you're not playing are just set aside.")

    roles = await asyncio.to_thread(repo.role_summary, chat_id, bot)
    role_lines = [f"{'✅' if r['active'] else '▫️'} {kind}: {md(r['active'] or '-')}"
                  + (f" (set aside: {md(', '.join(r['parked']))})" if r["parked"] else "")
                  for kind, r in roles.items()]
    await update.effective_message.reply_text(
        text + "\n\n" + "\n".join(role_lines), parse_mode="Markdown", reply_markup=ReplyKeyboardRemove()
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

async def org_claim(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Claim/Reserve on a new-food alert: the org this chat represents claims it (same atomic claim as the web)."""
    query = update.callback_query
    donation_id = query.data.split(":", 1)[1]
    org = await asyncio.to_thread(repo.get_org, update.effective_chat.id, context.bot.username)
    if not org:
        await query.answer("Only registered partner organizations can claim here. Send /start to register.",
                           show_alert=True)
        return
    try:
        claim = await asyncio.to_thread(repo.claim_donation, donation_id, str(org["id"]))
    except repo.NotAvailable:
        if await already_yours(query, donation_id, org["id"]):
            return
        await query.answer("Already claimed or no longer available 😔")
        await query.edit_message_text(f"{query.message.text}\n\n😔 Someone else got this one first, or it's no longer available.")
        return
    await query.answer("It's yours! 🎉")
    await offer_messages.close(donation_id, claim, bot_edit(context), skip_message_id=query.message.message_id)
    directions = f"https://www.google.com/maps/dir/?api=1&destination={claim['lat']},{claim['lng']}"
    paid = (f"🛒 Reserved for *₱{float(claim['reserved_price']):g}*: pay the donor in person at pickup.\n\n"
            if claim["reserved_price"] is not None else "")
    await query.edit_message_text(
        f"✅ *Claimed for {md(org['name'])}:* {md(claim['food_type'])} ({md(claim['quantity'])})\n\n"
        f"{paid}📍 Pick it up here: {directions}\n\n"
        "📸 When you have it, *send a photo of it here* to confirm the pickup.",
        parse_mode="Markdown",
        reply_markup=map_only(),
    )
    await tg_out.send_message(claim["donor_chat_id"], notify.claimed_text(claim))


async def flash_claim(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """🙋 on a flash offer: first tap wins (same atomic claim as the web app)."""
    query = update.callback_query
    donation_id = query.data.split(":", 1)[1]
    person = await asyncio.to_thread(repo.get_individual, update.effective_chat.id, context.bot.username)
    if not person or not person["active"]:
        await query.answer("Flash offers are for people on the list. Send /start and choose 'I need food'.", show_alert=True)
        return
    try:
        claim = await asyncio.to_thread(repo.claim_donation, donation_id, str(person["id"]))
    except repo.NotAvailable:
        if await already_yours(query, donation_id, person["id"]):
            return
        await query.answer("Someone else got it first 😔")
        await query.edit_message_text(
            f"{query.message.text}\n\n😔 Someone else got this one first. I'll message you about the next one."
        )
        return
    await query.answer("It's yours! 🎉")
    await query.edit_message_text(offer_messages.yours_text(claim), parse_mode="Markdown")
    await offer_messages.close(donation_id, claim, bot_edit(context), skip_message_id=query.message.message_id)
    await tg_out.send_message(claim["donor_chat_id"], notify.claimed_text(claim))


def bot_edit(context: ContextTypes.DEFAULT_TYPE):
    """offer_messages.Edit through this bot (so tests' fake Telegram sees it too)."""
    async def edit(chat_id: int, message_id: int, text: str):
        return await context.bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=text,
                                                   parse_mode="Markdown", disable_web_page_preview=True)
    return edit


async def already_yours(query, donation_id: str, recipient_id) -> bool:
    """A tap on an old offer/alert for food this chat already claimed (e.g. on the map): say so and
    show the pickup details, instead of 'someone else got it'."""
    claim = await asyncio.to_thread(repo.claim_of, donation_id)
    if not claim or str(claim["recipient_id"]) != str(recipient_id):
        return False
    await query.answer("You already claimed this 👍")
    await query.edit_message_text(offer_messages.yours_text(claim), parse_mode="Markdown")
    return True


def _time_left(expires_at) -> str:
    if isinstance(expires_at, str):
        expires_at = datetime.fromisoformat(expires_at)
    mins = max(0, int((expires_at - datetime.now(timezone.utc)).total_seconds() // 60))
    return f"{mins // 60}h {mins % 60:02d}m" if mins >= 60 else f"{mins} min"


def my_listings_view(listings: list[dict]) -> tuple[str, InlineKeyboardMarkup | None]:
    """The /mylistings message: one line per listing, a 'Mark as gone' button per unclaimed one."""
    if not listings:
        return "You have no live listings right now. Send a photo whenever you have food to share 📸", None
    waiting = [d for d in listings if d["status"] != "claimed"]
    claimed = [d for d in listings if d["status"] == "claimed"]
    lines, rows = ["📋 *Your live listings*"], []
    if waiting:
        lines += ["", "*Waiting for a taker*"]
        for d in waiting:
            state = "🚨 no takers yet" if d["status"] == "escalated" else "📡 open"
            if d["listing_type"] == "sale" and d["current_price"] is not None:
                state += f" · 🏷️ ₱{float(d['current_price']):g}"
            lines.append(f"• {md(d['food_type'])} ({md(d['quantity'])})\n   {state} · ⏱ {_time_left(d['expires_at'])} left")
            # the button names the food, so it's clear which listing it removes
            rows.append([InlineKeyboardButton(f"🗑️ Take down: {d['food_type'][:28]}", callback_data=f"gone:{d['id']}")])
    if claimed:
        lines += ["", "*Being picked up* (can't be taken down)"]
        for d in claimed:
            who = f"*{md(d['claimer_name'] or 'someone')}*"
            status = (f"✔️ by {who}, they're coming" if _time_left(d["expires_at"]) != "0 min"
                      else f"⌛ pickup window over; closes within the hour if {who} didn't collect it")
            lines.append(f"• {md(d['food_type'])} ({md(d['quantity'])})\n   {status}")
    if rows:
        lines += ["", "Already given away or eaten? Tap *Take down* below so no one makes a wasted trip."]
    return "\n".join(lines), InlineKeyboardMarkup(rows) if rows else None


async def my_listings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    donor = await asyncio.to_thread(repo.get_donor_by_chat, update.effective_chat.id)
    if not donor:
        await update.effective_message.reply_text("You haven't shared food yet. Send /start to set up your donor profile.")
        return
    text, keyboard = my_listings_view(await asyncio.to_thread(repo.my_active_listings, donor["id"]))
    await update.effective_message.reply_text(text, parse_mode="Markdown", reply_markup=keyboard)


async def mark_gone(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    donation_id = query.data.split(":", 1)[1]
    donor = await asyncio.to_thread(repo.get_donor_by_chat, update.effective_chat.id)
    if not donor:
        await query.answer("Only the donor can take this listing down.", show_alert=True)
        return
    try:
        gone = await asyncio.to_thread(repo.withdraw_donation, donation_id, donor["id"])
        await query.answer(f"Taken down: {gone['food_type']}")
    except repo.NotAvailable:
        claimer = await asyncio.to_thread(repo.claimer_of, donation_id)
        await query.answer(
            f"Already claimed by {claimer}, they're coming for it." if claimer else "This listing has already ended.",
            show_alert=True,
        )
    # Re-render the list so it reflects what's live now
    text, keyboard = my_listings_view(await asyncio.to_thread(repo.my_active_listings, donor["id"]))
    try:
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=keyboard)
    except Exception:  # noqa: BLE001 - e.g. message unchanged or too old to edit
        await update.effective_message.reply_text(text, parse_mode="Markdown", reply_markup=keyboard)


async def stop_offers(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    was_on = await asyncio.to_thread(repo.set_individual_active, update.effective_chat.id, context.bot.username, False)
    await update.effective_message.reply_text(
        "🔕 Done. You won't get flash offers anymore. Send /start → 'I need food' to turn them back on."
        if was_on
        else "You're not on the flash-offer list right now. Send /start → 'I need food' to join."
    )


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
        # Only blame the connection when it actually was one; a bug shouldn't read as "try again later"
        network = isinstance(context.error, (NetworkError, psycopg.OperationalError, httpx.HTTPError))
        reason = "a connection hiccup, please try again" if network else "our mistake, and it's been logged"
        try:
            await update.effective_message.reply_text(
                f"😕 Something went wrong on our side ({reason}).\n\n"
                "If you were posting food, just send the photo again to start over. Otherwise, send /start."
            )
        except Exception:  # noqa: BLE001 - e.g. Telegram itself unreachable; the log has the details
            pass


# ---------------------------------------------------------------------------

def build_application(token: str, request=None, persistence=None) -> Application:
    """`request` lets tests swap in a fake Telegram HTTP layer.
    `persistence` (e.g. DbPersistence) keeps conversations and drafts across restarts."""
    builder = Application.builder().token(token)
    if request is not None:
        builder = builder.request(request).get_updates_request(request)
    else:
        # PTB's 5 s defaults time out on slow venue/mobile wifi; give replies room to get through
        builder = builder.connect_timeout(10).read_timeout(20).write_timeout(20).pool_timeout(10)
    if persistence is not None:
        builder = builder.persistence(persistence)
    app = builder.build()
    persistent = persistence is not None
    text = filters.TEXT & ~filters.COMMAND
    # /demo mid-conversation must end it too, or the old draft would keep answering
    fallbacks = [CommandHandler("cancel", cancel), CommandHandler("demo", demo_switch)]

    onboarding = ConversationHandler(
        entry_points=[
            CommandHandler("start", start),
            CommandHandler("profile", edit_profile),
            # role buttons (e.g. "I also have food to share") start their branch even outside a conversation
            CallbackQueryHandler(chose_role, pattern=r"^role:"),
        ],
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
            ORG_PICK: [CallbackQueryHandler(org_picked, pattern=r"^orglink:")],
            ORG_NAME: [MessageHandler(text, got_org_name)],
            ORG_KIND: [CallbackQueryHandler(chose_org_kind, pattern=r"^okind:")],
            ORG_LOCATION: [MessageHandler(filters.LOCATION, got_org_location), MessageHandler(text, location_expected)],
            ORG_RADIUS: [CallbackQueryHandler(chose_org_radius, pattern=r"^orad:")],
            ORG_HOURS: [MessageHandler(text, got_org_hours)],
            ORG_CAPACITY: [MessageHandler(text, got_org_capacity)],
            IND_NAME: [MessageHandler(text, got_individual_name),
                       CallbackQueryHandler(got_individual_name, pattern=r"^indname:tg$")],
            IND_LOCATION: [
                MessageHandler(filters.LOCATION, got_individual_location),
                MessageHandler(text, location_expected),
            ],
        },
        fallbacks=fallbacks,
        allow_reentry=True,
        name="onboarding",
        persistent=persistent,
    )

    posting = ConversationHandler(
        entry_points=[MessageHandler(filters.PHOTO, got_photo)],
        states={
            AI_CONFIRM: [CallbackQueryHandler(chose_ai, pattern=r"^ai:")],
            LISTING_TYPE: [CallbackQueryHandler(chose_listing_type, pattern=r"^lt:")],
            PRICE: [CallbackQueryHandler(got_price, pattern=r"^price:"), MessageHandler(text, got_price)],
            PHOTO_PURPOSE: [CallbackQueryHandler(chose_photo_purpose, pattern=r"^purpose:")],
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
        persistent=persistent,
    )

    app.add_handler(onboarding)
    app.add_handler(posting)
    # Same group, registered last: only reached when no conversation handled the update
    app.add_handler(CallbackQueryHandler(flash_claim, pattern=r"^flash:"))  # works mid-conversation too
    app.add_handler(CallbackQueryHandler(org_claim, pattern=r"^oclaim:"))
    app.add_handler(CommandHandler("stop", stop_offers))
    app.add_handler(CommandHandler("mylistings", my_listings))
    app.add_handler(CallbackQueryHandler(mark_gone, pattern=r"^gone:"))
    app.add_handler(CommandHandler("cancel", cancel))
    app.add_handler(CommandHandler("demo", demo_switch))
    app.add_handler(CallbackQueryHandler(stale_button))
    app.add_handler(MessageHandler(text, unexpected_text))
    app.add_error_handler(on_error)
    return app
