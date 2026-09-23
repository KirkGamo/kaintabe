from pathlib import Path

import pytest

from app import db

JARO = "00000000-0000-0000-0000-00000000a001"
LA_PAZ = "00000000-0000-0000-0000-00000000a002"
CITY_PROPER = "00000000-0000-0000-0000-00000000a003"
DEMO_DONOR = "00000000-0000-0000-0000-00000000d003"  # Household in Jaro


@pytest.fixture
def conn():
    """DB connection whose changes are rolled back after the test."""
    c = db.connect()
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
