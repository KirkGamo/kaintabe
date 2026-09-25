"""Keep flash-offer / org-alert messages in step with reality once food is claimed.

Whoever claimed it (in the bot or on the map) sees "✅ It's yours" with directions in place of the
offer; everyone else who got the same offer sees "claimed by someone else". Buttons are removed, so
nobody taps a dead offer.
"""
import asyncio
import logging
from collections.abc import Awaitable, Callable

from app.services import repo
from app.services.notify import md

log = logging.getLogger(__name__)

# edit(chat_id, message_id, text): the bot's edit_message_text in handlers, the HTTP API in routes
Edit = Callable[[int, int, str], Awaitable[object]]


def yours_text(claim: dict) -> str:
    """The claimer's copy: what they claimed, where to get it, and how to confirm."""
    paid = (f"🛒 Reserved for *₱{float(claim['reserved_price']):g}*: pay the donor in person at pickup.\n\n"
            if claim.get("reserved_price") is not None else "")
    return (
        f"✅ *It's yours!* {md(claim['food_type'])} ({md(claim['quantity'])})\n\n"
        f"{paid}📍 Pick it up here: https://www.google.com/maps/dir/?api=1&destination={claim['lat']},{claim['lng']}\n\n"
        "📸 When you have it, *send a photo of it here* to confirm the pickup."
    )


def taken_text(food_type: str) -> str:
    return f"😔 {md(food_type)} was claimed by someone else first. I'll message you about the next one."


async def close(donation_id: str, claim: dict, edit: Edit, skip_message_id: int | None = None) -> int:
    """Update every offer/alert message for this claimed listing. `claim` has recipient_id,
    food_type, quantity, lat, lng (and reserved_price). Best effort: returns how many were edited."""
    rows = await asyncio.to_thread(repo.offer_messages, donation_id)
    edited = 0
    for r in rows:
        if r["message_id"] == skip_message_id:  # the message the claimer just tapped: already updated
            continue
        text = yours_text(claim) if str(r["recipient_id"]) == str(claim["recipient_id"]) else taken_text(claim["food_type"])
        try:
            await edit(r["chat_id"], r["message_id"], text)
            edited += 1
        except Exception as e:  # noqa: BLE001 - a deleted/old message mustn't stop the rest
            log.info("could not update offer message %s in %s: %s", r["message_id"], r["chat_id"], type(e).__name__)
    return edited
