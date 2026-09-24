"""Auto-widen / escalate / expire SQL functions (run directly, inside a rolled-back transaction)."""
import pytest
from tests.conftest import CITY_PROPER, insert_donation


def set_config(conn, key, value):
    conn.execute("update app_config set value = %s where key = %s", (value, key))


def row(conn, donation_id):
    return conn.execute("select status, search_radius_m, radius_widened_at from donations where id = %s",
                        (donation_id,)).fetchone()


def age(conn, donation_id, minutes):
    """Pretend the last widening happened `minutes` ago."""
    conn.execute("update donations set radius_widened_at = now() - make_interval(mins => %s) where id = %s",
                 (minutes, donation_id))


def test_widen_doubles_after_interval_then_caps_then_escalates(conn):
    set_config(conn, "widen_after_minutes", 10)
    d = insert_donation(conn, radius_m=2000)

    conn.execute("select widen_unclaimed()")
    assert row(conn, d)["search_radius_m"] == 2000  # too early

    age(conn, d, 11)
    conn.execute("select widen_unclaimed()")
    assert row(conn, d)["search_radius_m"] == 4000
    assert row(conn, d)["status"] == "posted"

    conn.execute("select widen_unclaimed()")
    assert row(conn, d)["search_radius_m"] == 4000  # interval restarts after each widening

    age(conn, d, 11)
    conn.execute("select widen_unclaimed()")
    assert row(conn, d)["search_radius_m"] == 8000  # max

    age(conn, d, 11)
    conn.execute("select widen_unclaimed()")
    r = row(conn, d)
    assert r["search_radius_m"] == 8000 and r["status"] == "escalated"


def test_widening_brings_listing_into_range(conn):
    d = insert_donation(conn, radius_m=2000)  # next to Jaro; City Proper is ~3.2 km away
    ids = lambda: [r["id"] for r in conn.execute("select id from nearby_donations(%s)", (CITY_PROPER,))]
    assert d not in ids()
    age(conn, d, 60)
    conn.execute("select widen_unclaimed()")
    assert d in ids()


def test_claimed_and_expired_are_left_alone(conn):
    claimed = insert_donation(conn, status="claimed")
    expired = insert_donation(conn, expires_at_sql="now() - interval '1 minute'")
    for d in (claimed, expired):
        age(conn, d, 60)
    conn.execute("select widen_unclaimed()")
    assert row(conn, claimed)["search_radius_m"] == 2000
    assert row(conn, expired)["search_radius_m"] == 2000


def test_expire_marks_past_due_open_listings(conn):
    past = insert_donation(conn, expires_at_sql="now() - interval '1 minute'")
    escalated_past = insert_donation(conn, status="escalated", expires_at_sql="now() - interval '1 minute'")
    future = insert_donation(conn)
    claimed_past = insert_donation(conn, status="claimed", expires_at_sql="now() - interval '1 minute'")

    conn.execute("select expire_donations()")
    assert row(conn, past)["status"] == "expired"
    assert row(conn, escalated_past)["status"] == "expired"
    assert row(conn, future)["status"] == "posted"
    assert row(conn, claimed_past)["status"] == "claimed"  # already matched: pickup still happens


def test_fractional_demo_interval(conn):
    set_config(conn, "widen_after_minutes", 0.5)  # demo mode: 30 s
    d = insert_donation(conn)
    conn.execute("update donations set radius_widened_at = now() - interval '31 seconds' where id = %s", (d,))
    conn.execute("select widen_unclaimed()")
    assert row(conn, d)["search_radius_m"] == 4000


def test_cron_job_scheduled(conn):
    job = conn.execute("select schedule, command, active from cron.job where jobname = 'kaintabe-tick'").fetchone()
    assert job["active"] and job["command"] == "select public.kaintabe_tick()"


# --- claimed but never picked up (017) ---------------------------------------------------

def claimed_expired(conn, minutes_past_expiry):
    from tests.conftest import JARO
    d = insert_donation(conn, expires_at_sql=f"now() - interval '{minutes_past_expiry} minutes'")
    conn.execute("update donations set status = 'claimed' where id = %s", (d,))
    claim = conn.execute("insert into claims (donation_id, recipient_id) values (%s, %s) returning id", (d, JARO)).fetchone()
    return d, claim["id"]


def test_claimed_listing_closes_an_hour_after_expiry(conn):
    within_grace, _ = claimed_expired(conn, 30)
    past_grace, _ = claimed_expired(conn, 61)
    conn.execute("select expire_donations()")
    assert row(conn, within_grace)["status"] == "claimed"  # can still confirm a just-in-time pickup
    assert row(conn, past_grace)["status"] == "expired"


def test_confirm_refused_after_listing_closed(conn):
    import psycopg
    d, claim_id = claimed_expired(conn, 61)
    conn.execute("select expire_donations()")
    with pytest.raises(psycopg.errors.RaiseException, match="not_confirmable"):
        with conn.transaction():
            conn.execute("select * from confirm_pickup(%s, %s)", (claim_id, "https://example.com/late.jpg"))
    assert row(conn, d)["status"] == "expired"


def test_confirm_within_grace_still_counts(conn):
    d, claim_id = claimed_expired(conn, 30)
    conn.execute("select * from confirm_pickup(%s, %s)", (claim_id, "https://example.com/p.jpg"))
    assert row(conn, d)["status"] == "completed"
