from pathlib import Path

import pytest

from app import db

JARO = "00000000-0000-0000-0000-00000000a001"
LA_PAZ = "00000000-0000-0000-0000-00000000a002"
CITY_PROPER = "00000000-0000-0000-0000-00000000a003"
DEMO_DONOR = "00000000-0000-0000-0000-00000000d003"  # Household in Jaro


SEED_SQL = Path(__file__).resolve().parents[2] / "supabase" / "seed.sql"


@pytest.fixture(scope="session", autouse=True)
def seed_rows():
    """Tests use the seeded pantries and demo donors. The live database may have been emptied
    (demo.py wipe --all), so add them for this run if missing and remove what we added afterwards."""
    with db.connect() as c:
        had = {r["id"] for r in c.execute("select id from recipients union all select id from donors")}
        c.execute(SEED_SQL.read_text(encoding="utf-8"))  # idempotent: on conflict do nothing
        added = [str(r["id"]) for r in c.execute("select id from recipients union all select id from donors")
                 if r["id"] not in had and str(r["id"]).startswith("00000000-0000-0000-0000-")]
    yield
    if added:
        with db.connect() as c:
            c.execute("delete from claims where recipient_id = any(%s::uuid[])"
                      " or donation_id in (select id from donations where donor_id = any(%s::uuid[]))", (added, added))
            c.execute("delete from donations where donor_id = any(%s::uuid[])", (added,))
            c.execute("delete from recipients where id = any(%s::uuid[])", (added,))
            c.execute("delete from donors where id = any(%s::uuid[])", (added,))


@pytest.fixture
def conn():
    """DB connection whose changes are rolled back after the test.

    The SQL tests were written for a 2 km start and 8 km max reach; pin those here (rolled back
    with everything else) so tuning the live app_config doesn't break them."""
    c = db.connect()
    c.execute("update app_config set value = 2000 where key = 'radius_start_m'")
    c.execute("update app_config set value = 8000 where key = 'radius_max_m'")
    try:
        yield c
    finally:
        c.rollback()
        c.close()


def insert_donation(conn, lat=10.7250, lng=122.5575, radius_m=2000, **overrides):
    row = {
        "donor_id": DEMO_DONOR,
        "donor_name": "Household in Jaro",
        "food_type": "test pancit",
        "quantity": "5 trays",
        "lat": lat,
        "lng": lng,
        "search_radius_m": radius_m,
        "expires_at_sql": "now() + interval '4 hours'",
        **overrides,
    }
    expires = row.pop("expires_at_sql")
    cols = ", ".join(row)
    vals = ", ".join(f"%({k})s" for k in row)
    return conn.execute(
        f"insert into donations ({cols}, expires_at) values ({vals}, {expires}) returning id", row
    ).fetchone()["id"]


@pytest.fixture(scope="session")
def frontend_env():
    env = {}
    for line in (Path(__file__).resolve().parents[2] / "frontend" / ".env").read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    return env


# --- signed Telegram Mini App identities for API tests ---------------------------------------

API_BOT = "api_test_bot"
API_ORG_SPOTS = {  # same places as the seeded pantries, so range behavior is identical
    "jaro": (10.7245, 122.5570, -210001),
    "lapaz": (10.7128, 122.5700, -210002),
    "cityproper": (10.6965, 122.5645, -210003),
}


@pytest.fixture
def api_orgs(monkeypatch):
    """Three test partner orgs linked to fake Telegram users of a fake bot, plus signed headers for each."""
    from app import tg_auth
    from app.config import settings

    monkeypatch.setattr(tg_auth, "_bot_username", API_BOT)
    ids = {}
    with db.connect() as conn:
        # leftovers of an interrupted run (teardown never ran) would break the unique chat+bot index
        stale = "select id from recipients where via_bot = %s"
        conn.execute(f"delete from claims where recipient_id in ({stale})", (API_BOT,))
        conn.execute("delete from recipients where via_bot = %s", (API_BOT,))
        for name, (lat, lng, tg_id) in API_ORG_SPOTS.items():
            ids[name] = str(conn.execute(
                "insert into recipients (name, type, lat, lng, service_radius_m, telegram_chat_id, via_bot) "
                "values (%s, 'partner_org', %s, %s, 8000, %s, %s) returning id",
                (f"API Org {name}", lat, lng, tg_id, API_BOT),
            ).fetchone()["id"])

    def headers(name=None, tg_id=None):
        uid = tg_id if tg_id is not None else API_ORG_SPOTS[name][2]
        init = tg_auth.sign_init_data({"id": uid, "first_name": "Tester"}, settings.telegram_bot_token)
        return {"X-Telegram-Init-Data": init}

    yield ids, headers
    with db.connect() as conn:
        conn.execute("delete from claims where recipient_id = any(%s::uuid[])", (list(ids.values()),))
        conn.execute("delete from recipients where id = any(%s::uuid[])", (list(ids.values()),))
