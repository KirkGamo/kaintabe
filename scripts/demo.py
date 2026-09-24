"""Stage helper: plays the people you don't have a second phone for.

Your phone plays one role at a time in the real bot (switch with /demo donor|org|individual in the chat).
This script plays the others, on the same database and through the same rules the app uses:
  - a stand-in partner org (one of the seeded pantries) that claims and picks up your food
  - stand-in donors (the seeded demo donors) that post food near your org

Notifications go to your phone through the chosen bot (prod by default), exactly as the real ones do.
Needs PROD_TELEGRAM_BOT_TOKEN and DEMO_CHAT_ID in backend/.env (never committed).

Usage (from repo root):
    backend/.venv/Scripts/python scripts/demo.py status             # timers, your roles, live listings
    backend/.venv/Scripts/python scripts/demo.py prepare            # demo timers on, sample history, tidy up
    backend/.venv/Scripts/python scripts/demo.py post               # stand-in donor posts ~0.8 km from your org
    backend/.venv/Scripts/python scripts/demo.py post --far         # ~2.6 km away: reaches your org after it widens
    backend/.venv/Scripts/python scripts/demo.py post --sale 150    # a discount sale instead
    backend/.venv/Scripts/python scripts/demo.py claim              # stand-in org claims your newest listing
    backend/.venv/Scripts/python scripts/demo.py confirm            # ...and confirms the pickup (thank-you to you)
    backend/.venv/Scripts/python scripts/demo.py escalate           # jump a listing to 8 km + flash offers now
    backend/.venv/Scripts/python scripts/demo.py reset              # real timers back, remove stand-in listings
    backend/.venv/Scripts/python scripts/demo.py wipe [--yes]       # start from scratch (keeps seed + sample history)
Add --bot dev to any command to use the dev bot (local rehearsal) instead of prod.
"""
import argparse
import asyncio
import math
import random
import subprocess
import sys
from pathlib import Path

import httpx
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app import db  # noqa: E402
from app.config import ENV_FILE, settings  # noqa: E402
from app.services import notify, repo, storage, telegram  # noqa: E402

PROD_WEB_URL = "https://appcon2026-team-triecode-kaintabe.vercel.app"
DEMO_MINUTES = 1
REAL_TIMERS = {"widen_after_minutes": 10, "sale_window_minutes": 60}

STANDIN_DONORS = {
    "bakery": "00000000-0000-0000-0000-00000000d001",      # Panaderia sa Mandurriao
    "carinderia": "00000000-0000-0000-0000-00000000d002",  # Molo Carinderia
    "household": "00000000-0000-0000-0000-00000000d003",   # Household in Jaro
}
STANDIN_ORGS = [  # seeded pantries; only ones nobody has linked to Telegram are used
    "00000000-0000-0000-0000-00000000a001",  # Bayanihan Pantry Jaro
    "00000000-0000-0000-0000-00000000a002",  # La Paz Community Kitchen
    "00000000-0000-0000-0000-00000000a003",  # City Proper Food Hub
]
FOODS = [
    ("Pandesal", "40 pieces", 2.0), ("Chicken adobo with rice", "12 packs", 4.0),
    ("Pancit canton", "3 trays", 4.5), ("Assorted kakanin", "25 pieces", 2.5),
    ("Lumpiang shanghai", "60 pieces", 2.0), ("Puto and kutsinta", "30 pieces", 1.8),
]
SIM_MARK = {"hygienic": True, "safe_temperature": True, "contents_known": True, "simulated": True}
KM_LAT = 1 / 111.0  # degrees of latitude per km


# --- setup ---------------------------------------------------------------------------

class Ctx:
    bot: str       # bot username (recipients.via_bot)
    chat_id: int   # your Telegram chat


def setup(which: str) -> Ctx:
    env = dotenv_values(ENV_FILE)
    if which == "prod":
        token = env.get("PROD_TELEGRAM_BOT_TOKEN")
        if not token:
            sys.exit("PROD_TELEGRAM_BOT_TOKEN is missing from backend/.env")
        settings.telegram_bot_token = token
        settings.web_url = PROD_WEB_URL
    if not env.get("DEMO_CHAT_ID"):
        sys.exit("DEMO_CHAT_ID (your Telegram chat id) is missing from backend/.env")
    res = httpx.get(f"https://api.telegram.org/bot{settings.telegram_bot_token}/getMe", timeout=15)
    res.raise_for_status()
    ctx = Ctx()
    ctx.bot = res.json()["result"]["username"]
    ctx.chat_id = int(env["DEMO_CHAT_ID"])
    return ctx


def find_listing(conn, prefix: str | None, statuses: tuple, mine_first_chat: int | None = None) -> dict:
    """The listing whose id starts with `prefix`, else the newest one in `statuses`."""
    if prefix:
        row = conn.execute(
            "select * from donations where id::text like %s and status = any(%s) order by created_at desc limit 1",
            (prefix + "%", list(statuses)),
        ).fetchone()
    else:
        row = conn.execute(
            """
            select d.* from donations d join donors o on o.id = d.donor_id
             where d.status = any(%s) and (d.expires_at > now() or d.status = 'claimed')
             order by (o.telegram_chat_id = %s) desc nulls last, d.created_at desc limit 1
            """,
            (list(statuses), mine_first_chat),
        ).fetchone()
    if not row:
        sys.exit(f"No listing found ({'/'.join(statuses)}{', id ' + prefix if prefix else ''}).")
    return row


def left(mins) -> str:
    return f"{float(mins):.0f} min left" if mins > 0 else "expired"


# --- commands ------------------------------------------------------------------------

def cmd_status(ctx: Ctx, a) -> None:
    with db.connect() as conn:
        timers = {r["key"]: float(r["value"]) for r in conn.execute("select key, value from app_config")}
        live = conn.execute(
            """
            select d.id, d.food_type, d.status, d.listing_type, d.current_price, d.search_radius_m,
                   d.expires_at, d.donor_name, r.name claimer, (d.safety_checklist ? 'simulated') sim,
                   extract(epoch from (d.expires_at - now())) / 60 mins_left
              from donations d left join claims c on c.donation_id = d.id
              left join recipients r on r.id = c.recipient_id
             where d.status in ('posted', 'escalated', 'claimed') and d.expires_at > now() - interval '1 hour'
             order by d.created_at desc
            """
        ).fetchall()
        history = conn.execute(
            "select count(*) n from donations where safety_checklist @> '{\"seed_history\": true}'"
        ).fetchone()["n"]
    demo = timers["widen_after_minutes"] < REAL_TIMERS["widen_after_minutes"]
    print(f"bot: @{ctx.bot}   timers: widen {timers['widen_after_minutes']:g} min, "
          f"sale {timers['sale_window_minutes']:g} min ({'DEMO' if demo else 'real'})   sample history: {history}")
    summary = repo.role_summary(ctx.chat_id, ctx.bot)
    person = repo.get_individual(ctx.chat_id, ctx.bot)
    for role, r in summary.items():
        now = r["active"] or "-"
        if role == "individual" and person and not person["active"]:
            now += "  <- paused (/stop); /demo individual turns it back on"
        parked = f"   (set aside: {', '.join(r['parked'])})" if r["parked"] else ""
        print(f"  you as {role:<10}: {now}{parked}")
    print(f"live listings ({len(live)}):")
    for d in live:
        price = f" P{float(d['current_price']):g}" if d["current_price"] is not None else ""
        who = f" -> {d['claimer']}" if d["claimer"] else ""
        print(f"  {str(d['id'])[:8]}  {d['status']:<9} {d['food_type']}{price} from {d['donor_name']}{who}"
              f"  [{d['search_radius_m'] / 1000:g} km, {left(d['mins_left'])}]{'  (stand-in)' if d['sim'] else ''}")


def cmd_prepare(ctx: Ctx, a) -> None:
    with db.connect() as conn:
        for key in REAL_TIMERS:
            conn.execute("update app_config set value = %s where key = %s", (a.minutes, key))
        has_history = conn.execute(
            "select count(*) n from donations where safety_checklist @> '{\"seed_history\": true}'"
        ).fetchone()["n"]
    print(f"demo timers on: widen and sale window every {a.minutes:g} min")
    if not has_history:
        subprocess.run([sys.executable, str(ROOT / "scripts" / "seed_demo_history.py")], check=True)
    n = remove_standin_listings()
    if n:
        print(f"removed {n} leftover stand-in listings")
    print()
    cmd_status(ctx, a)
    summary = repo.role_summary(ctx.chat_id, ctx.bot)
    todo = [f"{kind}: /demo fresh, then /start -> {how}" for kind, how in (
        ("donor", "I have food to share"),
        ("org", "We're a community kitchen / org -> Register a new organization (5 km)"),
        ("individual", "I need food"),
    ) if not summary[kind]["active"] and not summary[kind]["parked"]]
    if todo:
        print(f"\nOn your phone (@{ctx.bot}):")
        for t in todo:
            print(f"  - {t}")


def post_anchor(ctx: Ctx) -> dict | None:
    """Where stand-in food goes: near the role you're playing now (org first), else a set-aside one."""
    with db.connect() as conn:
        return conn.execute(
            """
            select r.* from recipients r left join demo_parked p on p.row_id = r.id
             where r.via_bot = %s and (r.telegram_chat_id = %s or p.chat_id = %s)
             order by (r.telegram_chat_id is not null) desc, (r.type = 'partner_org') desc, p.parked_at desc
             limit 1
            """,
            (ctx.bot, ctx.chat_id, ctx.chat_id),
        ).fetchone()


def cmd_post(ctx: Ctx, a) -> None:
    org = post_anchor(ctx)
    if not org:
        sys.exit(f"You have no org or individual on @{ctx.bot} yet, so there's nowhere to post near.")
    km = 2.6 if a.far else 0.8  # far: past the 2 km start, inside 4 km and a 3 km personal reach
    angle = random.uniform(0, 6.283)
    lat = org["lat"] + km * KM_LAT * math.sin(angle)
    lng = org["lng"] + km * KM_LAT * math.cos(angle) / math.cos(math.radians(org["lat"]))
    with db.connect() as conn:
        donor = conn.execute("select * from donors where id = %s", (STANDIN_DONORS[a.donor],)).fetchone()
    food, qty, kg = random.choice(FOODS)
    d = repo.create_donation(
        donor=donor, photo_url=None,
        food_type=a.food or food, quantity=a.qty or qty, est_kg=a.kg if a.kg is not None else kg,
        lat=lat, lng=lng, good_for_hours=a.hours,
        safety_checklist=SIM_MARK, listing_type="sale" if a.sale else "donation", price=a.sale,
    )
    print(f"{donor['name']} posted {d['food_type']} ({d['quantity']}) {km:g} km from {org['name']}"
          f"{f' for P{a.sale:g}' if a.sale else ''}  id={str(d['id'])[:8]}")
    if a.far:
        print("It starts with a 2 km search radius; your org gets the alert once it widens to 4 km "
              "(about one widen period).")
    else:
        print("If you're playing the org (/demo org), its alert arrives within a few seconds.")


def standin_org_for(d: dict) -> dict:
    """The nearest unlinked seeded pantry the listing's current radius reaches."""
    with db.connect() as conn:
        row = conn.execute(
            """
            select r.*, st_distance(d.location, r.location) dist from recipients r, donations d
             where d.id = %s and r.id = any(%s) and r.telegram_chat_id is null
               and st_dwithin(d.location, r.location, d.search_radius_m)
             order by dist limit 1
            """,
            (d["id"], STANDIN_ORGS),
        ).fetchone()
    if not row:
        sys.exit(f"No stand-in pantry is within this listing's {d['search_radius_m'] / 1000:g} km radius yet. "
                 "Wait for it to widen, or run: demo.py escalate")
    return row


def cmd_claim(ctx: Ctx, a) -> None:
    with db.connect() as conn:
        d = find_listing(conn, a.id, ("posted", "escalated"), ctx.chat_id)
    org = standin_org_for(d)
    try:
        claim = repo.claim_donation(str(d["id"]), str(org["id"]))
    except repo.NotAvailable:
        sys.exit("Someone else got it first (or it expired).")
    sent = asyncio.run(telegram.send_message(claim["donor_chat_id"], notify.claimed_text(claim)))
    print(f"{org['name']} claimed {d['food_type']} ({claim['distance_m'] / 1000:.1f} km)  id={str(d['id'])[:8]}"
          f"  donor notified: {'yes' if sent else 'no (stand-in donor or send failed)'}")


def cmd_confirm(ctx: Ctx, a) -> None:
    with db.connect() as conn:
        d = find_listing(conn, a.id, ("claimed",), ctx.chat_id)
        claim = conn.execute(
            "select c.*, (r.telegram_chat_id is null and r.id = any(%s)) standin from claims c "
            "join recipients r on r.id = c.recipient_id where c.donation_id = %s",
            (STANDIN_ORGS, d["id"]),
        ).fetchone()
    if not claim["standin"]:
        sys.exit("That pickup belongs to a real org or person; they confirm it themselves.")
    photo = None
    if d["photo_url"]:  # the stand-in "photographs" the food it collected: reuse the listing's photo
        try:
            photo = httpx.get(d["photo_url"], timeout=20).raise_for_status().content
        except httpx.HTTPError:
            photo = None
    photo_url = asyncio.run(storage.upload_photo("pickup-photos", photo)) if photo else (d["photo_url"] or "")
    try:
        done = repo.confirm_pickup(str(claim["id"]), photo_url)
    except repo.NotAvailable:
        sys.exit("Already confirmed, or the listing closed.")
    text = notify.picked_up_text(done)
    send = telegram.send_photo(done["donor_chat_id"], photo, text) if photo else \
        telegram.send_message(done["donor_chat_id"], text)
    sent = asyncio.run(send)
    print(f"{done['recipient_name']} picked up {done['food_type']}  -> {done['status']}"
          f"  donor thanked: {'yes' if sent else 'no (stand-in donor or send failed)'}")


def cmd_escalate(ctx: Ctx, a) -> None:
    """Skip the widening steps: max radius + escalated now, so flash offers go out on the next tick."""
    with db.connect() as conn:
        d = find_listing(conn, a.id, ("posted",), None)
        if d["listing_type"] != "donation":
            sys.exit("Sales turn into free donations first; only donations escalate.")
        conn.execute(
            "update donations set search_radius_m = (select value::int from app_config where key = 'radius_max_m'),"
            " radius_widened_at = now(), status = 'escalated' where id = %s and status = 'posted'",
            (d["id"],),
        )
    print(f"{d['food_type']} escalated to the max radius; flash offers go to opted-in individuals nearby "
          "within a few seconds.")


def remove_standin_listings() -> int:
    """Delete the stand-in donors' live-demo listings (the sample history stays)."""
    live_sim = ("safety_checklist @> '{\"simulated\": true}' "
                "and not safety_checklist @> '{\"seed_history\": true}'")
    with db.connect() as conn:
        conn.execute(f"delete from claims where donation_id in (select id from donations where {live_sim})")
        return conn.execute(f"delete from donations where {live_sim}").rowcount


SEEDED_INDIVIDUALS = ["00000000-0000-0000-0000-00000000b001", "00000000-0000-0000-0000-00000000b002"]
# coalesce: the earliest listings predate the checklist (null), and "not null" would skip them
NOT_HISTORY = "not (coalesce(safety_checklist, '{}') @> '{\"seed_history\": true}')"


def cmd_wipe(ctx: Ctx, a) -> None:
    """Start from scratch: delete every real/test listing, donor and recipient; keep the seed + sample history."""
    keep_donors = list(STANDIN_DONORS.values())
    keep_recipients = STANDIN_ORGS + SEEDED_INDIVIDUALS
    with db.connect() as conn:
        listings = conn.execute(
            f"select status, count(*) n from donations where {NOT_HISTORY} group by status order by status"
        ).fetchall()
        donors = conn.execute("select name, telegram_chat_id from donors where id <> all(%s::uuid[]) order by name",
                              (keep_donors,)).fetchall()
        recipients = conn.execute(
            "select name, type, via_bot from recipients where id <> all(%s::uuid[]) order by type, name",
            (keep_recipients,),
        ).fetchall()
        links = conn.execute(
            "select name, via_bot from recipients where id = any(%s::uuid[]) and telegram_chat_id is not null",
            (keep_recipients,),
        ).fetchall()
        history = conn.execute(f"select count(*) n from donations where not {NOT_HISTORY}").fetchone()["n"]

        def names(rows, fmt):
            return ", ".join(fmt.format(**r) for r in rows) or "none"

        print("Will DELETE (permanently):")
        print(f"  listings: {names(listings, '{n} {status}')} (and their claims)")
        print(f"  donors ({len(donors)}): {names(donors, '{name}')}")
        print(f"  orgs/individuals ({len(recipients)}): {names(recipients, '{name} ({type}, {via_bot})')}")
        if links:
            print(f"  Telegram links of seeded orgs: {names(links, '{name} ({via_bot})')}")
        print(f"Will KEEP: {history} sample-history pickups, the 3 seeded pantries, 2 seeded individuals, "
              "3 stand-in donors, settings.")
        if not a.yes:
            print("\nNothing deleted. Run again with --yes to do it.")
            return

        with conn.transaction():
            conn.execute(
                f"delete from claims where donation_id in (select id from donations where {NOT_HISTORY})"
                " or recipient_id <> all(%s::uuid[])", (keep_recipients,),
            )
            conn.execute(f"delete from donations where {NOT_HISTORY}")
            conn.execute("delete from demo_parked")
            conn.execute("delete from recipients where id <> all(%s::uuid[])", (keep_recipients,))
            conn.execute(
                "update recipients set telegram_chat_id = null, via_bot = null, review_status = 'approved',"
                " active = true where id = any(%s::uuid[])", (keep_recipients,),
            )
            conn.execute("delete from donors where id <> all(%s::uuid[])", (keep_donors,))
    print("\nWiped. Everyone (including you) starts fresh: send /start to the bot. "
          "If a chat was mid-question, send /cancel first.")


def cmd_reset(ctx: Ctx, a) -> None:
    with db.connect() as conn:
        for key, value in REAL_TIMERS.items():
            conn.execute("update app_config set value = %s where key = %s", (value, key))
    print(f"real timers back: widen {REAL_TIMERS['widen_after_minutes']} min, "
          f"sale window {REAL_TIMERS['sale_window_minutes']} min")
    print(f"removed {remove_standin_listings()} stand-in listings (sample history kept)")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--bot", choices=["prod", "dev"], default="prod")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    s = sub.add_parser("prepare")
    s.add_argument("--minutes", type=float, default=DEMO_MINUTES)
    s = sub.add_parser("post")
    s.add_argument("--far", action="store_true", help="~2.6 km away instead of ~0.8 km")
    s.add_argument("--donor", choices=STANDIN_DONORS, default="bakery")
    s.add_argument("--food")
    s.add_argument("--qty")
    s.add_argument("--kg", type=float)
    s.add_argument("--hours", type=float, default=4)
    s.add_argument("--sale", type=float, metavar="PRICE")
    for name in ("claim", "confirm", "escalate"):
        s = sub.add_parser(name)
        s.add_argument("id", nargs="?", help="listing id prefix (default: newest; yours first)")
    sub.add_parser("reset")
    s = sub.add_parser("wipe")
    s.add_argument("--yes", action="store_true", help="actually delete (default: only show what would go)")
    a = p.parse_args()

    ctx = setup(a.bot)
    globals()[f"cmd_{a.cmd}"](ctx, a)


if __name__ == "__main__":
    main()
