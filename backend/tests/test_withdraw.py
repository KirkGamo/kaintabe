"""R2 SQL: withdraw_donation rules, and withdrawn listings drop out of every active path (rolled back)."""
import psycopg
import pytest

from tests.conftest import DEMO_DONOR, JARO, insert_donation

OTHER_DONOR = "00000000-0000-0000-0000-00000000d001"


def status(conn, d):
    return conn.execute("select status from donations where id = %s", (d,)).fetchone()["status"]


def withdraw(conn, d, donor=DEMO_DONOR):
    return conn.execute("select * from withdraw_donation(%s, %s)", (d, donor)).fetchone()


@pytest.mark.parametrize("start", ["posted", "escalated"])
def test_withdraw_open_listing(conn, start):
    d = insert_donation(conn, status=start)
    assert withdraw(conn, d)["status"] == "withdrawn"


@pytest.mark.parametrize("start", ["claimed", "completed", "sold", "expired", "withdrawn"])
def test_cannot_withdraw_ended_or_claimed(conn, start):
    d = insert_donation(conn, status=start)
    with pytest.raises(psycopg.errors.RaiseException, match="not_withdrawable"):
        with conn.transaction():
            withdraw(conn, d)
    assert status(conn, d) == start


def test_cannot_withdraw_someone_elses(conn):
    d = insert_donation(conn)  # belongs to DEMO_DONOR
    with pytest.raises(psycopg.errors.RaiseException, match="not_withdrawable"):
        with conn.transaction():
            withdraw(conn, d, donor=OTHER_DONOR)
    assert status(conn, d) == "posted"


def test_withdrawn_is_invisible_and_untouched(conn):
    d = insert_donation(conn, radius_m=2000)
    withdraw(conn, d)
    assert d not in [r["id"] for r in conn.execute("select id from nearby_donations(%s)", (JARO,))]
    with pytest.raises(psycopg.errors.RaiseException, match="not_available"):
        with conn.transaction():
            conn.execute("select * from claim_donation(%s, %s)", (d, JARO))
    conn.execute("update donations set radius_widened_at = now() - interval '1 hour', "
                 "expires_at = now() - interval '1 minute' where id = %s", (d,))
    conn.execute("select widen_unclaimed(), expire_donations()")
    row = conn.execute("select status, search_radius_m from donations where id = %s", (d,)).fetchone()
    assert (row["status"], row["search_radius_m"]) == ("withdrawn", 2000)


def test_claim_then_withdraw_race(conn):
    d = insert_donation(conn)
    conn.execute("select * from claim_donation(%s, %s)", (d, JARO))  # claim lands first
    with pytest.raises(psycopg.errors.RaiseException, match="not_withdrawable"):
        with conn.transaction():
            withdraw(conn, d)
    assert status(conn, d) == "claimed"
