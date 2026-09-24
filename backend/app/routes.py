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


@router.get("/map")
async def role_map(user: dict = Depends(tg_auth.telegram_user)):
    """Exact map data for this Telegram user's roles only (the public map is approximate):
       org        -> listings within its reach + its own pending pickups
       individual -> their own pending pickups (flash offers they claimed)
       donor      -> their own live/claimed listings
    """
    chat_id, bot = int(user["id"]), await tg_auth.bot_username()
    org, person, donor = await asyncio.gather(
        asyncio.to_thread(repo.get_org, chat_id, bot),
        asyncio.to_thread(repo.get_individual, chat_id, bot),
        asyncio.to_thread(repo.get_donor_by_chat, chat_id),
    )
    in_range, pickups, mine = await asyncio.gather(
        asyncio.to_thread(repo.listings_in_range, org["id"]) if org else asyncio.sleep(0, []),
        asyncio.to_thread(repo.pending_pickups, [r["id"] for r in (org, person) if r]),
        asyncio.to_thread(repo.donor_listings, donor["id"]) if donor else asyncio.sleep(0, []),
    )
    return {
        "first_name": user.get("first_name"),
        "org": _public_org(org),
        "individual": {"lat": person["lat"], "lng": person["lng"], "active": person["active"]} if person else None,
        "donor": {"id": donor["id"], "name": donor["name"], "type": donor["type"], "lat": donor["lat"],
                  "lng": donor["lng"]} if donor else None,
        "in_range": in_range,
        "my_pickups": pickups,
        "my_listings": mine,
    }


@router.post("/listings/{donation_id}/withdraw")
async def withdraw_listing(donation_id: UUID, user: dict = Depends(tg_auth.telegram_user)):
    """A donor takes down their own unclaimed listing (same rule as the bot's /mylistings)."""
    donor = await asyncio.to_thread(repo.get_donor_by_chat, int(user["id"]))
    if not donor:
        raise HTTPException(403, "Only the donor can take this listing down.")
    try:
        gone = await asyncio.to_thread(repo.withdraw_donation, str(donation_id), donor["id"])
    except repo.NotAvailable:
        raise HTTPException(409, "It's already claimed (or no longer live), so it can't be taken down.")
    return {"id": gone["id"], "status": gone["status"]}


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
    recipient_id: UUID | None = Form(default=None),  # ignored: who is confirming comes from Telegram
    user: dict = Depends(tg_auth.telegram_user),
):
    # Whoever claimed it confirms it: a partner org, or an individual who took a flash offer
    chat_id, bot = int(user["id"]), await tg_auth.bot_username()
    org, person = await asyncio.gather(
        asyncio.to_thread(repo.get_org, chat_id, bot),
        asyncio.to_thread(repo.get_individual, chat_id, bot),
    )
    mine = {r["id"] for r in (org, person) if r}
    if not mine:
        raise HTTPException(403, "Only the person or organization that claimed this food can confirm the pickup.")
    claim = await asyncio.to_thread(repo.get_claim, str(claim_id))
    if not claim:
        raise HTTPException(404, "Claim not found.")
    if claim["recipient_id"] not in mine:
        raise HTTPException(403, "This pickup was claimed by someone else.")
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
