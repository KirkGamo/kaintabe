"""Donor-facing Telegram texts, shared by the web API and the bot (flash-offer claims)."""
from telegram.helpers import escape_markdown

KG_PER_MEAL = 0.4  # same factor as the impact dashboard


def md(text) -> str:
    """Escape user-provided text for parse_mode="Markdown"."""
    return escape_markdown(str(text), version=1)


def claimed_text(claim: dict) -> str:
    """Sent to the donor when a kitchen, buyer or individual claims their listing."""
    item = f"{md(claim['food_type'])} ({md(claim['quantity'])})"
    who = f"*{md(claim['recipient_name'])}*, {claim['distance_m'] / 1000:.1f} km away"
    if claim["reserved_price"] is not None:
        return (
            f"🛒 *Reserved!* Your {item} was reserved by {who}.\n\n"
            f"They'll pay you *₱{float(claim['reserved_price']):g}* in person at pickup (cash or GCash). "
            "Please keep it ready. 💚"
        )
    return (
        f"🎉 *Claimed!* Your {item} was claimed by {who}.\n\n"
        "They're coming to pick it up. Please keep it ready. "
        "You'll get a thank-you once pickup is confirmed. 💚"
    )


def picked_up_text(done: dict) -> str:
    """Caption on the pickup photo sent to the donor once pickup is confirmed."""
    impact = ""
    if done["est_kg"]:
        kg = float(done["est_kg"])
        meals = max(1, round(kg / KG_PER_MEAL))
        impact = f"You rescued ~{kg:g} kg ≈ {meals} meal{'' if meals == 1 else 's'}. "
    item = f"{md(done['food_type'])} ({md(done['quantity'])})"
    if done["reserved_price"] is not None:
        return (
            f"✅ *Sold and picked up!* Your {item} went to *{md(done['recipient_name'])}* "
            f"for ₱{float(done['reserved_price']):g}.\n\n{impact}Salamat for not letting it go to waste! 💚"
        )
    return f"✅ *Picked up!* Your {item} is now with *{md(done['recipient_name'])}*.\n\n{impact}Salamat for sharing! 💚"
