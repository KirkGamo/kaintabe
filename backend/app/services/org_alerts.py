"""New-food alerts for partner orgs: a claimable listing is within reach -> Telegram message with Claim."""
import asyncio
import logging
from datetime import datetime, timezone

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo

from app.config import settings
from app.services import repo
from app.services.notify import md

log = logging.getLogger(__name__)


def alert_text(a: dict) -> str:
    hours_left = max(0, (a["expires_at"] - datetime.now(timezone.utc)).total_seconds() / 3600)
    good_for = f"{hours_left:.0f} hrs" if hours_left >= 1 else f"{hours_left * 60:.0f} min"
    lines = [
        "🍱 *New food near you*",
        "",
        f"{md(a['food_type'])} ({md(a['quantity'])})",
        f"📍 from {md(a['donor_name'])}, {a['distance_m'] / 1000:.1f} km away",
        f"⏱ Good for about {good_for}",
    ]
    if a["listing_type"] == "sale" and a["current_price"] is not None:
        lines.append(f"🏷️ For sale: about ₱{float(a['current_price']):g}, paid at pickup (the price keeps dropping)")
    lines += ["", "First to claim gets it."]
    return "\n".join(lines)


def alert_keyboard(a: dict) -> InlineKeyboardMarkup:
    sale = a["listing_type"] == "sale"
    rows = [[InlineKeyboardButton("🛒 Reserve (pay at pickup)" if sale else "✅ Claim, free pickup",
                                  callback_data=f"oclaim:{a['donation_id']}")]]
    if settings.map_url:
        rows.append([InlineKeyboardButton("🗺️ Open map", web_app=WebAppInfo(url=settings.map_url))])
    return InlineKeyboardMarkup(rows)


async def send_pending(bot) -> int:
    """Send every new in-range alert for this bot's partner orgs. Returns how many went out."""
    alerts = await asyncio.to_thread(repo.claim_org_alerts, bot.username)
    sent = 0
    for a in alerts:
        try:
            await bot.send_message(chat_id=a["chat_id"], text=alert_text(a), parse_mode="Markdown",
                                   reply_markup=alert_keyboard(a))
            sent += 1
        except Exception as e:  # noqa: BLE001 - one unreachable org mustn't stop the rest
            log.warning("org alert to %s failed: %s", a["chat_id"], type(e).__name__)
    if alerts:
        log.info("org alerts: %s sent of %s", sent, len(alerts))
    return sent
