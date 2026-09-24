import threading

import httpx
import psycopg
import pytest

from app import db
from tests.conftest import CITY_PROPER, JARO, LA_PAZ, insert_donation


def nearby_ids(conn, recipient_id):
    return [r["id"] for r in conn.execute("select * from nearby_donations(%s)", (recipient_id,))]


def test_seed_loaded(conn):
    # the 3 seeded pantries exist (orgs may also self-register through the bot, so don't count all of them)
    seeded = conn.execute(
        "select id::text from recipients where type = 'partner_org' and id = any(%s::uuid[])",
        ([JARO, LA_PAZ, CITY_PROPER],),
    ).fetchall()
    assert len(seeded) == 3


def test_nearby_respects_radius_and_orders_by_distance(conn):
    donation = insert_donation(conn, radius_m=2000)  # next to the Jaro pantry

    # Jaro (~70 m) and La Paz (~1.9 km) are within 2 km; City Proper (~3.2 km) is not
    assert donation in nearby_ids(conn, JARO)
    assert donation in nearby_ids(conn, LA_PAZ)
    assert donation not in nearby_ids(conn, CITY_PROPER)

    dist = {
        r["id"]: r["distance_m"]
        for r in conn.execute(
            "select r.id::text id, st_distance(d.location, r.location) distance_m"
            " from donations d, recipients r where d.id = %s",
            (donation,),
        )
    }
    assert dist[JARO] < dist[LA_PAZ] < 2000 < dist[CITY_PROPER]

    # Widening the radius brings City Proper into range
    conn.execute("update donations set search_radius_m = 4000 where id = %s", (donation,))
    assert donation in nearby_ids(conn, CITY_PROPER)


def test_nearby_sorted_nearest_first(conn):
    near = insert_donation(conn, lat=10.7246, lng=122.5571)
    far = insert_donation(conn, lat=10.7330, lng=122.5570, radius_m=2000)  # ~950 m north
    rows = conn.execute("select id, distance_m from nearby_donations(%s)", (JARO,)).fetchall()
    ids = [r["id"] for r in rows]
    assert ids.index(near) < ids.index(far)
    assert [r["distance_m"] for r in rows] == sorted(r["distance_m"] for r in rows)


def test_nearby_hides_expired_and_claimed(conn):
    expired = insert_donation(conn, expires_at_sql="now() - interval '1 minute'")
    claimed = insert_donation(conn, status="claimed")
    ids = nearby_ids(conn, JARO)
    assert expired not in ids and claimed not in ids


def test_claim_then_second_claim_rejected(conn):
    donation = insert_donation(conn)
    claim = conn.execute("select * from claim_donation(%s, %s)", (donation, JARO)).fetchone()
    assert str(claim["recipient_id"]) == JARO
    assert conn.execute("select status from donations where id = %s", (donation,)).fetchone()["status"] == "claimed"

    with pytest.raises(psycopg.errors.RaiseException, match="not_available"):
        with conn.transaction():  # savepoint so the outer test tx survives
            conn.execute("select * from claim_donation(%s, %s)", (donation, LA_PAZ))


def test_claim_out_of_range_rejected(conn):
    donation = insert_donation(conn, radius_m=2000)
    with pytest.raises(psycopg.errors.RaiseException, match="not_available"):
        conn.execute("select * from claim_donation(%s, %s)", (donation, CITY_PROPER))


def test_confirm_pickup_completes_donation(conn):
    donation = insert_donation(conn)
    claim = conn.execute("select * from claim_donation(%s, %s)", (donation, JARO)).fetchone()
    conn.execute("select * from confirm_pickup(%s, %s)", (claim["id"], "https://example.com/p.jpg"))
    assert conn.execute("select status from donations where id = %s", (donation,)).fetchone()["status"] == "completed"
    with pytest.raises(psycopg.errors.RaiseException, match="not_confirmable"):
        conn.execute("select * from confirm_pickup(%s, %s)", (claim["id"], "x"))


def test_concurrent_claims_only_one_wins():
    """Two orgs tap Claim at the same moment on separate connections."""
    setup = db.connect()
    donation = insert_donation(setup)
    setup.commit()

    results = {}
    barrier = threading.Barrier(2)

    def claim(recipient):
        with db.connect() as c:
            barrier.wait()
            try:
                c.execute("select * from claim_donation(%s, %s)", (donation, recipient))
                c.commit()
                results[recipient] = "won"
            except psycopg.errors.RaiseException:
                results[recipient] = "lost"

    try:
        threads = [threading.Thread(target=claim, args=(r,)) for r in (JARO, LA_PAZ)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert sorted(results.values()) == ["lost", "won"]
        assert setup.execute("select count(*) n from claims where donation_id = %s", (donation,)).fetchone()["n"] == 1
    finally:
        setup.execute("delete from claims where donation_id = %s", (donation,))
        setup.execute("delete from donations where id = %s", (donation,))
        setup.commit()
        setup.close()


def test_anon_key_is_read_only(frontend_env):
    """The browser key can read listings but not donors, and can't claim."""
    base = frontend_env["VITE_SUPABASE_URL"].rstrip("/") + "/rest/v1"
    key = frontend_env["VITE_SUPABASE_ANON_KEY"]
    h = {"apikey": key, "Authorization": f"Bearer {key}"}

    assert httpx.get(f"{base}/donations?select=id&limit=1", headers=h).status_code == 200
    assert httpx.get(f"{base}/recipients?select=id,name,lat,lng", headers=h).status_code == 200
    assert httpx.get(f"{base}/recipients?select=telegram_chat_id", headers=h).status_code in (401, 403)
    assert httpx.get(f"{base}/donors?select=*", headers=h).json() == []  # RLS: no rows visible
    r = httpx.post(f"{base}/rpc/claim_donation", headers=h,
                   json={"p_donation_id": "00000000-0000-0000-0000-000000000000", "p_recipient_id": JARO})
    assert r.status_code in (401, 403, 404)
    r = httpx.post(f"{base}/rpc/nearby_donations", headers=h, json={"p_recipient_id": JARO})
    assert r.status_code == 200
