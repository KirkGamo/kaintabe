"""HTTP API used by the web app. The browser only reads via Supabase; state changes come here."""
import asyncio
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from app.bot.handlers import md
from app.services import repo, storage, telegram

router = APIRouter(prefix="/api")

MAX_PHOTO_BYTES = 10 * 1024 * 1024
KG_PER_MEAL = 0.4  # same factor as the impact dashboard


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


@router.post("/claims/{claim_id}/confirm")
async def confirm_claim(
    claim_id: UUID,
    background: BackgroundTasks,
    recipient_id: UUID = Form(...),
    photo: UploadFile = File(...),
):
    claim = await asyncio.to_thread(repo.get_claim, str(claim_id))
    if not claim:
        raise HTTPException(404, "Claim not found.")
    if claim["recipient_id"] != recipient_id:
        raise HTTPException(403, "This pickup belongs to another organization.")
    if claim["confirmed_at"]:
        raise HTTPException(409, "This pickup was already confirmed.")
    if not (photo.content_type or "").startswith("image/"):
        raise HTTPException(422, "Please upload a photo.")
    data = await photo.read()
    if not data:
        raise HTTPException(422, "The photo is empty.")
    if len(data) > MAX_PHOTO_BYTES:
        raise HTTPException(413, "Photo is too large (max 10 MB).")

    photo_url = await storage.upload_photo("pickup-photos", data, photo.content_type)
    try:
        done = await asyncio.to_thread(repo.confirm_pickup, str(claim_id), photo_url)
    except repo.NotAvailable:
        raise HTTPException(409, "This pickup was already confirmed.")

    impact = ""
    if done["est_kg"]:
        kg = float(done["est_kg"])
        impact = f"You rescued ~{kg:g} kg ≈ {max(1, round(kg / KG_PER_MEAL))} meals. "
    background.add_task(
        telegram.send_photo,
        done["donor_chat_id"],
        data,
        f"✅ *Picked up!* Your {md(done['food_type'])} ({md(done['quantity'])}) "
        f"is now with *{md(done['recipient_name'])}*.\n\n{impact}Salamat for sharing! 💚",
    )
    return {
        "id": done["id"],
        "donation_id": done["donation_id"],
        "confirmed_at": done["confirmed_at"],
        "confirmation_photo_url": photo_url,
        "donation_status": done["status"],
    }
