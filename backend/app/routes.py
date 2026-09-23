"""HTTP API used by the web app. The browser only reads via Supabase; state changes come here."""
import asyncio
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from app.services import notify, repo, storage, telegram

router = APIRouter(prefix="/api")

MAX_PHOTO_BYTES = 10 * 1024 * 1024


class ClaimRequest(BaseModel):
    donation_id: UUID
    recipient_id: UUID


@router.post("/claims", status_code=201)
async def create_claim(body: ClaimRequest, background: BackgroundTasks):
    try:
        claim = await asyncio.to_thread(repo.claim_donation, str(body.donation_id), str(body.recipient_id))
    except repo.NotAvailable:
        raise HTTPException(409, "This listing was just claimed by someone else or is no longer available.")

    background.add_task(telegram.send_message, claim["donor_chat_id"], notify.claimed_text(claim))
    return {
        "id": claim["id"],
        "donation_id": claim["donation_id"],
        "recipient_id": claim["recipient_id"],
        "claimed_at": claim["claimed_at"],
        "reserved_price": claim["reserved_price"],
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

    background.add_task(telegram.send_photo, done["donor_chat_id"], data, notify.picked_up_text(done))
    return {
        "id": done["id"],
        "donation_id": done["donation_id"],
        "confirmed_at": done["confirmed_at"],
        "confirmation_photo_url": photo_url,
        "donation_status": done["status"],
    }
