"""AI photo intake: one Claude vision call turns a donor's food photo into listing fields.

Best effort by design: any failure (no key, timeout, refusal, API error) returns None and the
bot falls back to asking the donor the questions manually.
"""
import base64
import logging
from typing import Literal

import anthropic
from pydantic import BaseModel, Field

from app.config import settings

log = logging.getLogger(__name__)

TIMEOUT_S = 25


class FoodListing(BaseModel):
    is_food: bool = Field(description="False if the photo does not show edible food")
    food_type: str = Field(description='Short name a recipient would recognise, e.g. "Pandesal", "Chicken adobo with rice"')
    quantity: str = Field(description='Countable amount as a donor would say it, e.g. "about 30 pieces", "3 trays"')
    est_kg: float = Field(description="Estimated total weight in kilograms")
    good_for_hours: int = Field(description="Conservative estimate of hours it stays safe to eat from now")
    allergens: list[str] = Field(description='Likely common allergens, lowercase, e.g. ["wheat", "milk", "egg", "peanut", "shellfish", "fish", "soy"]')
    suggested_price_php: float = Field(description="Fair discounted resale price in Philippine pesos for the whole lot (about 40-60% off typical retail)")
    confidence: Literal["high", "medium", "low"]


SYSTEM = """You help food donors in the Philippines post surplus food for community kitchens.
Look at the photo (and the donor's caption, if any) and describe the food for a listing.

- Name it the way a Filipino recipient would (local dish names are good).
- Count or estimate the amount you can actually see; don't invent hidden food.
- Be conservative about how long it stays safe: cooked dishes with meat, seafood, rice or \
coconut milk left at room temperature: 2-4 hours; bread and baked goods: 8-24 hours; \
whole fruit and packaged items: 24 hours or more. Never exceed 48.
- List allergens only when the food likely contains them.
- If the donor's caption contradicts what you see, trust the caption for name and amount.
- If the photo isn't food, set is_food to false and fill the other fields with placeholders."""

_client: anthropic.AsyncAnthropic | None = None


def _get_client() -> anthropic.AsyncAnthropic:
    global _client
    if _client is None:
        _client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key, timeout=TIMEOUT_S, max_retries=1)
    return _client


def _clean(listing: FoodListing) -> FoodListing:
    """Clamp model output into the ranges the rest of the app expects."""
    listing.food_type = listing.food_type.strip()[:120] or "Food"
    listing.quantity = listing.quantity.strip()[:80] or "some"
    listing.est_kg = round(min(max(listing.est_kg, 0.1), 200), 1)
    listing.good_for_hours = min(max(listing.good_for_hours, 1), 48)
    listing.allergens = sorted({a.strip().lower() for a in listing.allergens if a.strip()})[:8]
    listing.suggested_price_php = round(max(listing.suggested_price_php, 0))
    return listing


def enabled() -> bool:
    return bool(settings.anthropic_api_key)


async def parse_food_photo(photo: bytes, caption: str | None = None) -> FoodListing | None:
    if not settings.anthropic_api_key:
        return None
    content: list[dict] = [
        {
            "type": "image",
            "source": {"type": "base64", "media_type": "image/jpeg", "data": base64.standard_b64encode(photo).decode()},
        },
        {"type": "text", "text": f'Donor\'s caption: "{caption}"' if caption else "No caption was given."},
    ]
    try:
        response = await _get_client().messages.parse(
            model=settings.ai_model,
            max_tokens=2000,
            system=SYSTEM,
            messages=[{"role": "user", "content": content}],
            output_config={"effort": "low"},  # simple extraction; keeps the donor's wait short
            output_format=FoodListing,
        )
    except anthropic.APIConnectionError as e:
        log.warning("AI intake unreachable: %s", type(e).__name__)
        return None
    except anthropic.APIStatusError as e:
        log.warning("AI intake API error %s: %s", e.status_code, e.message)
        return None
    except Exception:  # noqa: BLE001 - e.g. schema validation; never block posting
        log.exception("AI intake failed")
        return None

    if response.stop_reason != "end_turn" or response.parsed_output is None:
        log.warning("AI intake stopped: %s", response.stop_reason)
        return None
    return _clean(response.parsed_output)
