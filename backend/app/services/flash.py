"""Flash offers: push escalated listings to opted-in individuals nearby, first to tap gets it."""
import asyncio
import logging
from datetime import datetime, timezone

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from app.services import repo
from app.services.notify import md

log = logging.getLogger(__name__)


def offer_text(o: dict) -> str:
    hours_left = max(0, (o["expires_at"] - datetime.now(timezone.utc)).total_seconds() / 3600)
    good_for = f"{hours_left:.0f} hrs" if hours_left >= 1 else f"{hours_left * 60:.0f} min"
    return (
        "📣 *Flash offer near you!*\n\n"
        f"🍱 {md(o['food_type'])} ({md(o['quantity'])})\n"
        f"📍 from {md(o['donor_name'])}, {o['distance_m'] / 1000:.1f} km away\n"
        f"⏱ Good for about {good_for}\n\n"
        "No community kitchen could take it in time. It's *free*, and the first person to tap gets it."
    )


async def send_pending(bot) -> int:
    """Send every newly escalated offer for this bot's opted-in individuals. Returns how many went out."""
    offers = await asyncio.to_thread(repo.claim_flash_offers, bot.username)
    sent = 0
    for o in offers:
        try:
            msg = await bot.send_message(
                chat_id=o["chat_id"],
                text=offer_text(o),
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton("🙋 I'll pick it up", callback_data=f"flash:{o['donation_id']}")]]
                ),
            )
            sent += 1
            # remembered so the offer can be updated once someone claims the food (offer_messages)
            await asyncio.to_thread(repo.remember_offer_message, "flash", o["donation_id"], o["recipient_id"],
                                    msg.message_id)
        except Exception as e:  # noqa: BLE001 - one blocked/unreachable person mustn't stop the rest
            log.warning("flash offer to %s failed: %s", o["chat_id"], type(e).__name__)
    if offers:
        log.info("flash offers: %s sent of %s", sent, len(offers))
    return sent


