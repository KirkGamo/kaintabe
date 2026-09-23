"""ai_intake with the Anthropic client mocked (no network, no cost)."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import anthropic
import httpx2

from app.services import ai_intake

LISTING = dict(is_food=True, food_type="  Adobo  ", quantity="3 trays", est_kg=250.0, good_for_hours=100,
               allergens=["Soy", "soy ", ""], suggested_price_php=149.6, confidence="medium")


def fake_client(result=None, error=None):
    client = MagicMock()
    client.messages.parse = AsyncMock(side_effect=error) if error else AsyncMock(return_value=result)
    return client


def run(client, key="sk-test"):
    with patch.object(ai_intake, "_get_client", return_value=client), \
         patch.object(ai_intake.settings, "anthropic_api_key", key):
        return asyncio.run(ai_intake.parse_food_photo(b"\xff\xd8img", "adobo"))


def test_parses_and_clamps():
    resp = SimpleNamespace(stop_reason="end_turn", parsed_output=ai_intake.FoodListing(**LISTING))
    client = fake_client(resp)
    out = run(client)
    assert out.food_type == "Adobo" and out.est_kg == 200 and out.good_for_hours == 48
    assert out.allergens == ["soy"] and out.suggested_price_php == 150

    kwargs = client.messages.parse.await_args.kwargs
    assert kwargs["model"] == ai_intake.settings.ai_model
    assert kwargs["output_format"] is ai_intake.FoodListing
    image, text = kwargs["messages"][0]["content"]
    assert image["source"]["media_type"] == "image/jpeg" and 'adobo' in text["text"]


def test_no_key_skips_call():
    client = fake_client()
    assert run(client, key="") is None
    client.messages.parse.assert_not_awaited()


def test_refusal_or_truncation_returns_none():
    for reason in ("refusal", "max_tokens"):
        assert run(fake_client(SimpleNamespace(stop_reason=reason, parsed_output=None))) is None


def test_api_and_network_errors_return_none():
    req = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    errors = [
        anthropic.APIConnectionError(request=req),
        anthropic.RateLimitError("slow down", response=httpx2.Response(429, request=req), body=None),
        anthropic.InternalServerError("boom", response=httpx2.Response(500, request=req), body=None),
        ValueError("bad json"),
    ]
    for err in errors:
        assert run(fake_client(error=err)) is None
