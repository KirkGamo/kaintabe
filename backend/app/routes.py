"""HTTP API used by the web app. The browser only reads via Supabase; state changes come here."""
import asyncio
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel

from app.bot.handlers import md
from app.services import repo, telegram

router = APIRouter(prefix="/api")


class ClaimRequest(BaseModel):
    donation_id: UUID
    recipient_id: UUID


@router.post("/claims", status_code=201)
async def create_claim(body: ClaimRequest, background: BackgroundTasks):
    try:
        claim = await asyncio.to_thread(repo.claim_donation, str(body.donation_id), str(body.recipient_id))
    except repo.NotAvailable:
        raise HTTPException(409, "This listing was just claimed by someone else or is no longer available.")

    km = claim["distance_m"] / 1000
    background.add_task(
        telegram.send_message,
        claim["donor_chat_id"],
        f"🎉 *Claimed!* Your {md(claim['food_type'])} ({md(claim['quantity'])}) "
        f"was claimed by *{md(claim['recipient_name'])}*, {km:.1f} km away.\n\n"
        "They're coming to pick it up. Please keep it ready. "
        "You'll get a thank-you once pickup is confirmed. 💚",
    )
    return {
        "id": claim["id"],
        "donation_id": claim["donation_id"],
        "recipient_id": claim["recipient_id"],
        "claimed_at": claim["claimed_at"],
        "distance_m": round(claim["distance_m"]),
    }
