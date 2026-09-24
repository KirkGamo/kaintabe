"""Database access for the bot and API. Sync psycopg; call from async code via asyncio.to_thread."""
import psycopg

from app import db


class NotAvailable(Exception):
    """Listing was already claimed, expired, or is out of this recipient's range."""


def get_donor_by_chat(chat_id: int) -> dict | None:
    with db.connect() as conn:
        return conn.execute("select * from donors where telegram_chat_id = %s", (chat_id,)).fetchone()


def create_donor(chat_id: int, name: str, type_: str, lat: float, lng: float) -> dict:
    """Register (or re-register) a donor; re-running onboarding updates the profile."""
    with db.connect() as conn:
        return conn.execute(
            """
            insert into donors (telegram_chat_id, name, type, lat, lng, pledged_at)
            values (%s, %s, %s, %s, %s, now())
            on conflict (telegram_chat_id) do update
              set name = excluded.name, type = excluded.type,
                  lat = excluded.lat, lng = excluded.lng, pledged_at = now()
            returning *
            """,
            (chat_id, name, type_, lat, lng),
        ).fetchone()


def create_donation(
    *,
    donor: dict,
    photo_url: str | None,
    food_type: str,
    quantity: str,
    est_kg: float | None,
    lat: float,
    lng: float,
    good_for_hours: float,
    safety_checklist: dict | None = None,
    allergens: list[str] | None = None,
    ai_assisted: bool = False,
    suggested_price: float | None = None,
    listing_type: str = "donation",
    price: float | None = None,
) -> dict:
    with db.connect() as conn:
        return conn.execute(
            """
            insert into donations (donor_id, donor_name, photo_url, food_type, quantity, est_kg,
                                   lat, lng, safety_checklist, expires_at, search_radius_m,
                                   allergens, ai_assisted, suggested_price,
                                   listing_type, original_price, current_price)
            values (%(donor_id)s, %(donor_name)s, %(photo_url)s, %(food_type)s, %(quantity)s, %(est_kg)s,
                    %(lat)s, %(lng)s, %(safety)s, now() + make_interval(mins => %(minutes)s),
                    (select value::int from app_config where key = 'radius_start_m'),
                    %(allergens)s, %(ai_assisted)s, %(suggested_price)s,
                    %(listing_type)s, %(price)s, %(price)s)
            returning *
            """,
            {
                "donor_id": donor["id"],
                "donor_name": donor["name"],
                "photo_url": photo_url,
                "food_type": food_type,
                "quantity": quantity,
                "est_kg": est_kg,
                "lat": lat,
                "lng": lng,
                "safety": db.Json(safety_checklist) if safety_checklist is not None else None,
                "minutes": int(good_for_hours * 60),
                "allergens": allergens,
                "ai_assisted": ai_assisted,
                "suggested_price": suggested_price,
                "listing_type": listing_type,
                "price": price if listing_type == "sale" else None,
            },
        ).fetchone()


def sale_window_minutes() -> float:
    """How long a sale's price takes to fall before it becomes a free donation."""
    with db.connect() as conn:
        return float(conn.execute("select value from app_config where key = 'sale_window_minutes'").fetchone()["value"])


def claim_donation(donation_id: str, recipient_id: str) -> dict:
    """Atomically claim a listing (PostGIS range + status checked in SQL).

    Returns the claim joined with what the notifications need.
    """
    with db.connect() as conn:
        try:
            claim = conn.execute(
                "select * from claim_donation(%s, %s)", (donation_id, recipient_id)
            ).fetchone()
        except psycopg.errors.RaiseException as e:
            if "not_available" in str(e):
                raise NotAvailable from e
            raise
        details = conn.execute(
            """
            select d.food_type, d.quantity, d.lat, d.lng, d.listing_type,
                   o.telegram_chat_id as donor_chat_id,
                   r.name as recipient_name, r.hours as recipient_hours,
                   st_distance(d.location, r.location) as distance_m
              from donations d
              join donors o on o.id = d.donor_id
              join recipients r on r.id = %s
             where d.id = %s
            """,
            (recipient_id, donation_id),
        ).fetchone()
        return {**claim, **details}


def get_claim(claim_id: str) -> dict | None:
    with db.connect() as conn:
        return conn.execute("select * from claims where id = %s", (claim_id,)).fetchone()


def confirm_pickup(claim_id: str, photo_url: str) -> dict:
    """Mark the claim confirmed and the listing completed/sold; returns what the thank-you needs."""
    with db.connect() as conn:
        try:
            claim = conn.execute("select * from confirm_pickup(%s, %s)", (claim_id, photo_url)).fetchone()
        except psycopg.errors.RaiseException as e:
            if "not_confirmable" in str(e):
                raise NotAvailable from e
            raise
        details = conn.execute(
            """
            select d.food_type, d.quantity, d.est_kg, d.status, d.listing_type,
                   o.telegram_chat_id as donor_chat_id, r.name as recipient_name
              from donations d
              join donors o on o.id = d.donor_id
              join recipients r on r.id = %s
             where d.id = %s
            """,
            (claim["recipient_id"], claim["donation_id"]),
        ).fetchone()
        return {**claim, **details}


# --- individuals & flash offers -------------------------------------------------

def upsert_individual(chat_id: int, name: str, lat: float, lng: float, via_bot: str) -> dict:
    """Opt a person in to flash offers (or update their spot / re-activate after /stop)."""
    with db.connect() as conn:
        return conn.execute(
            """
            insert into recipients (name, type, lat, lng, service_radius_m, verified, telegram_chat_id, via_bot, active)
            values (%s, 'individual', %s, %s, 3000, false, %s, %s, true)
            on conflict (telegram_chat_id, via_bot, type) where telegram_chat_id is not null do update
              set name = excluded.name, lat = excluded.lat, lng = excluded.lng, active = true
            returning *
            """,
            (name, lat, lng, chat_id, via_bot),
        ).fetchone()


def get_individual(chat_id: int, via_bot: str) -> dict | None:
    with db.connect() as conn:
        return conn.execute(
            "select * from recipients where type = 'individual' and telegram_chat_id = %s and via_bot = %s",
            (chat_id, via_bot),
        ).fetchone()


def set_individual_active(chat_id: int, via_bot: str, active: bool) -> bool:
    """Returns False if nothing changed (never opted in, or already in that state)."""
    with db.connect() as conn:
        return conn.execute(
            "update recipients set active = %s where type = 'individual' and telegram_chat_id = %s and via_bot = %s"
            " and active is distinct from %s",
            (active, chat_id, via_bot, active),
        ).rowcount > 0


def claim_flash_offers(via_bot: str) -> list[dict]:
    """Reserve (and return) the flash offers this bot should send now; each is returned only once ever."""
    with db.connect() as conn:
        return conn.execute("select * from claim_flash_offers(%s)", (via_bot,)).fetchall()


def pending_pickup(recipient_id) -> dict | None:
    """The individual's most recent claim still waiting for a pickup photo (last 24 h)."""
    with db.connect() as conn:
        return conn.execute(
            """
            select c.id, d.food_type from claims c join donations d on d.id = c.donation_id
             where c.recipient_id = %s and c.confirmed_at is null and d.status = 'claimed'
               and c.claimed_at > now() - interval '24 hours'
             order by c.claimed_at desc limit 1
            """,
            (recipient_id,),
        ).fetchone()


# --- donor's own listings ----------------------------------------------------------

def my_active_listings(donor_id) -> list[dict]:
    """Up to 10 of the donor's listings that are still live or claimed, newest first."""
    with db.connect() as conn:
        return conn.execute(
            """
            select d.id, d.food_type, d.quantity, d.status, d.listing_type, d.current_price, d.expires_at,
                   r.name as claimer_name
              from donations d
              left join claims c on c.donation_id = d.id
              left join recipients r on r.id = c.recipient_id
             where d.donor_id = %s
               and (d.status = 'claimed' or (d.status in ('posted', 'escalated') and d.expires_at > now()))
             order by d.created_at desc
             limit 10
            """,
            (donor_id,),
        ).fetchall()


def withdraw_donation(donation_id: str, donor_id) -> dict:
    """Take down the donor's own unclaimed listing; NotAvailable if it was claimed/ended meanwhile."""
    with db.connect() as conn:
        try:
            return conn.execute("select * from withdraw_donation(%s, %s)", (donation_id, donor_id)).fetchone()
        except psycopg.errors.RaiseException as e:
            if "not_withdrawable" in str(e):
                raise NotAvailable from e
            raise


def claimer_of(donation_id: str) -> str | None:
    with db.connect() as conn:
        row = conn.execute(
            "select r.name from claims c join recipients r on r.id = c.recipient_id where c.donation_id = %s",
            (donation_id,),
        ).fetchone()
        return row["name"] if row else None


# --- partner orgs via Telegram ------------------------------------------------------

def get_org(chat_id: int, via_bot: str) -> dict | None:
    """The partner org this Telegram chat represents (through this bot), if any."""
    with db.connect() as conn:
        return conn.execute(
            "select * from recipients where type = 'partner_org' and telegram_chat_id = %s and via_bot = %s",
            (chat_id, via_bot),
        ).fetchone()


def unlinked_orgs() -> list[dict]:
    """Seeded partner orgs nobody has linked a Telegram account to yet."""
    with db.connect() as conn:
        return conn.execute(
            "select id, name from recipients where type = 'partner_org' and telegram_chat_id is null"
            " and id not in (select row_id from demo_parked) order by name"  # parked demo orgs aren't free
        ).fetchall()


def link_org(org_id: str, chat_id: int, via_bot: str) -> dict:
    """First come: link an existing org to this chat. NotAvailable if someone already did."""
    with db.connect() as conn:
        row = conn.execute(
            """
            update recipients set telegram_chat_id = %s, via_bot = %s, review_status = 'pending_review'
             where id = %s and type = 'partner_org' and telegram_chat_id is null
            returning *
            """,
            (chat_id, via_bot, org_id),
        ).fetchone()
    if not row:
        raise NotAvailable
    return row


def create_org(chat_id: int, via_bot: str, *, name: str, org_kind: str, lat: float, lng: float,
               service_radius_m: int, hours: str, capacity: str) -> dict:
    with db.connect() as conn:
        return conn.execute(
            """
            insert into recipients (name, type, org_kind, lat, lng, service_radius_m, hours, capacity,
                                    verified, review_status, telegram_chat_id, via_bot)
            values (%s, 'partner_org', %s, %s, %s, %s, %s, %s, false, 'pending_review', %s, %s)
            returning *
            """,
            (name, org_kind, lat, lng, service_radius_m, hours, capacity, chat_id, via_bot),
        ).fetchone()


def claim_org_alerts(via_bot: str) -> list[dict]:
    """Reserve (and return) new-food alerts this bot should send to partner orgs; each only once."""
    with db.connect() as conn:
        return conn.execute("select * from claim_org_alerts(%s)", (via_bot,)).fetchall()


def pending_pickup_for_chat(chat_id: int, via_bot: str) -> dict | None:
    """Most recent claim (last 24 h) awaiting a pickup photo, by any recipient this chat represents
    (an individual on the flash list and/or a partner org)."""
    with db.connect() as conn:
        return conn.execute(
            """
            select c.id, d.food_type from claims c
              join donations d on d.id = c.donation_id
              join recipients r on r.id = c.recipient_id
             where r.telegram_chat_id = %s and r.via_bot = %s
               and c.confirmed_at is null and d.status = 'claimed'  -- not once the listing closed
               and c.claimed_at > now() - interval '24 hours'
             order by c.claimed_at desc limit 1
            """,
            (chat_id, via_bot),
        ).fetchone()


# --- role-based map views (exact details only for the right person) -------------------

LISTING_COLS = """d.id, d.donor_name, d.photo_url, d.food_type, d.quantity, d.est_kg, d.lat, d.lng,
    d.listing_type, d.original_price, d.current_price, d.expires_at, d.search_radius_m,
    d.radius_widened_at, d.status, d.created_at, d.safety_checklist, d.allergens, d.ai_assisted,
    d.flash_offer_count"""


def listings_in_range(org_id) -> list[dict]:
    """Open listings whose current reach covers this org (the same rule claim_donation enforces)."""
    with db.connect() as conn:
        return conn.execute(
            f"""
            select {LISTING_COLS}, st_distance(d.location, r.location) as distance_m
              from donations d join recipients r on r.id = %s
             where d.status in ('posted', 'escalated') and d.expires_at > now()
               and st_dwithin(d.location, r.location, d.search_radius_m)
             order by distance_m
            """,
            (org_id,),
        ).fetchall()


def pending_pickups(recipient_ids: list) -> list[dict]:
    """Listings these recipients claimed and haven't confirmed yet, with the claim."""
    if not recipient_ids:
        return []
    with db.connect() as conn:
        return conn.execute(
            f"""
            select {LISTING_COLS}, c.id as claim_id, c.recipient_id, c.reserved_price, c.claimed_at
              from claims c join donations d on d.id = c.donation_id
             where c.recipient_id = any(%s::uuid[]) and c.confirmed_at is null and d.status = 'claimed'
             order by c.claimed_at desc
            """,
            ([str(r) for r in recipient_ids],),
        ).fetchall()


def donor_listings(donor_id) -> list[dict]:
    """The donor's own live or claimed listings, exact, with who claimed them."""
    with db.connect() as conn:
        return conn.execute(
            f"""
            select {LISTING_COLS}, r.name as claimer_name
              from donations d
              left join claims c on c.donation_id = d.id
              left join recipients r on r.id = c.recipient_id
             where d.donor_id = %s
               and (d.status = 'claimed' or (d.status in ('posted', 'escalated') and d.expires_at > now()))
             order by d.created_at desc
            """,
            (donor_id,),
        ).fetchall()


# --- demo role switch (owner-only /demo) ----------------------------------------------
# A parked role keeps its row; only the chat link is removed (and remembered in demo_parked).

ROLE_KINDS = ("donor", "org", "individual")
_RECIPIENT_TYPE = {"org": "partner_org", "individual": "individual"}


def _active_role(conn, kind: str, chat_id: int, via_bot: str) -> dict | None:
    if kind == "donor":
        return conn.execute("select * from donors where telegram_chat_id = %s", (chat_id,)).fetchone()
    return conn.execute(
        "select * from recipients where type = %s and telegram_chat_id = %s and via_bot = %s",
        (_RECIPIENT_TYPE[kind], chat_id, via_bot),
    ).fetchone()


def role_summary(chat_id: int, via_bot: str) -> dict:
    """{kind: {"active": name or None, "parked": [names, newest first]}} for this chat on this bot."""
    with db.connect() as conn:
        out = {}
        for kind in ROLE_KINDS:
            row = _active_role(conn, kind, chat_id, via_bot)
            table = "donors" if kind == "donor" else "recipients"
            parked = conn.execute(
                f"select t.name from demo_parked p join {table} t on t.id = p.row_id"
                " where p.kind = %s and p.chat_id = %s and p.via_bot = %s order by p.parked_at desc",
                (kind, chat_id, "" if kind == "donor" else via_bot),
            ).fetchall()
            out[kind] = {"active": row["name"] if row else None, "parked": [p["name"] for p in parked]}
        return out


def park_roles(chat_id: int, via_bot: str, kinds) -> list[str]:
    """Unlink these roles from the chat (remembering them); returns the kinds that were parked."""
    parked = []
    with db.connect() as conn:
        for kind in kinds:
            row = _active_role(conn, kind, chat_id, via_bot)
            if not row:
                continue
            table = "donors" if kind == "donor" else "recipients"
            conn.execute(f"update {table} set telegram_chat_id = null where id = %s", (row["id"],))
            conn.execute(
                "insert into demo_parked (kind, row_id, chat_id, via_bot) values (%s, %s, %s, %s)"
                " on conflict (kind, row_id) do update set parked_at = now()",
                (kind, row["id"], chat_id, "" if kind == "donor" else via_bot),
            )
            parked.append(kind)
    return parked


def restore_role(chat_id: int, via_bot: str, kind: str) -> dict | None:
    """Make this role active again: the current one if linked, else the most recently parked one."""
    with db.connect() as conn:
        if row := _active_role(conn, kind, chat_id, via_bot):
            return row
        p = conn.execute(
            "delete from demo_parked where (kind, row_id) = (select kind, row_id from demo_parked"
            " where kind = %s and chat_id = %s and via_bot = %s order by parked_at desc limit 1) returning row_id",
            (kind, chat_id, "" if kind == "donor" else via_bot),
        ).fetchone()
        if not p:
            return None
        table = "donors" if kind == "donor" else "recipients"
        return conn.execute(
            f"update {table} set telegram_chat_id = %s where id = %s returning *", (chat_id, p["row_id"])
        ).fetchone()
