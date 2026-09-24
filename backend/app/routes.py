"""HTTP API used by the web app. The browser only reads via Supabase; state changes come here.

Who is acting is proven by the Telegram Mini App `initData` (see tg_auth), never by an id the
client sends: a normal browser can view the map but cannot claim or confirm.
"""
import asyncio
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from app import tg_auth
from app.services import notify, repo, storage, telegram

router = APIRouter(prefix="/api")

MAX_PHOTO_BYTES = 10 * 1024 * 1024


class ClaimRequest(BaseModel):
    donation_id: UUID
    recipient_id: UUID | None = None  # ignored: the org comes from the verified Telegram user


async def current_org(user: dict = Depends(tg_auth.telegram_user)) -> dict:
    """The partner org the verified Telegram user represents, or 403."""
    org = await asyncio.to_thread(repo.get_org, int(user["id"]), await tg_auth.bot_username())
    if not org:
        raise HTTPException(403, "Only registered partner organizations can claim. Register in the KainTabe bot.")
    return org


def _public_org(org: dict | None) -> dict | None:
    if not org:
        return None
    keys = ("id", "name", "type", "org_kind", "review_status", "lat", "lng", "service_radius_m", "capacity", "hours")
    return {k: org[k] for k in keys}


@router.get("/config")
async def config():
    """Public: what the web app needs to link people to the bot."""
    return {"bot_username": await tg_auth.bot_username()}


@router.get("/me")
async def me(user: dict = Depends(tg_auth.telegram_user)):
    """Who opened the Mini App: their Telegram name and the org they represent (if any)."""
    org = await asyncio.to_thread(repo.get_org, int(user["id"]), await tg_auth.bot_username())
    return {"telegram_user": {"id": user["id"], "first_name": user.get("first_name")}, "org": _public_org(org)}


@router.post("/claims", status_code=201)
async def create_claim(body: ClaimRequest, background: BackgroundTasks, org: dict = Depends(current_org)):
    try:
        claim = await asyncio.to_thread(repo.claim_donation, str(body.donation_id), str(org["id"]))
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
    photo: UploadFile = File(...),
    recipient_id: UUID | None = Form(default=None),  # ignored: the org comes from the verified Telegram user
    org: dict = Depends(current_org),
):
    claim = await asyncio.to_thread(repo.get_claim, str(claim_id))
    if not claim:
        raise HTTPException(404, "Claim not found.")
    if claim["recipient_id"] != org["id"]:
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
