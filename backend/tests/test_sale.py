"""Sale tier SQL: price decay, conversion to donation, and price locked on reserve (rolled back)."""
from tests.conftest import JARO, insert_donation


def sale(conn, price=100, minutes_ago=0, **kw):
    d = insert_donation(conn, listing_type="sale", original_price=price, current_price=price, **kw)
    conn.execute("update donations set radius_widened_at = now() - make_interval(secs => %s) where id = %s",
                 (minutes_ago * 60, d))
    return d


def row(conn, d):
    return conn.execute("select listing_type, current_price, search_radius_m, status, radius_widened_at "
                        "from donations where id = %s", (d,)).fetchone()


def interval(conn, minutes):
    conn.execute("update app_config set value = %s where key = 'widen_after_minutes'", (minutes,))


def test_price_decays_linearly(conn):
    interval(conn, 10)
    fresh, half, late = sale(conn, 100, 0), sale(conn, 100, 5), sale(conn, 100, 9)
    conn.execute("select decay_sale_prices()")
    assert float(row(conn, fresh)["current_price"]) == 100
    assert float(row(conn, half)["current_price"]) == 50
    assert float(row(conn, late)["current_price"]) == 10


def test_price_never_hits_zero_before_conversion(conn):
    interval(conn, 10)
    d = sale(conn, 5, 9.9)
    conn.execute("select decay_sale_prices()")
    assert float(row(conn, d)["current_price"]) == 1


def test_unsold_sale_converts_to_free_donation(conn):
    interval(conn, 10)
    d = sale(conn, 100, 11)
    conn.execute("select decay_sale_prices()")
    r = row(conn, d)
    assert r["listing_type"] == "donation" and r["current_price"] is None
    assert r["search_radius_m"] == 2000  # widening starts fresh from here

    conn.execute("select widen_unclaimed()")
    assert row(conn, d)["search_radius_m"] == 2000  # its widen clock just restarted


def test_sale_listings_do_not_widen_or_escalate(conn):
    interval(conn, 10)
    d = sale(conn, 100, 11)
    conn.execute("select widen_unclaimed()")  # widen alone, without conversion
    r = row(conn, d)
    assert r["search_radius_m"] == 2000 and r["status"] == "posted"


def test_reserve_locks_current_price(conn):
    d = sale(conn, 80)
    conn.execute("update donations set current_price = 48 where id = %s", (d,))
    claim = conn.execute("select * from claim_donation(%s, %s)", (d, JARO)).fetchone()
    assert float(claim["reserved_price"]) == 48


def test_donation_claim_has_no_price(conn):
    d = insert_donation(conn)
    claim = conn.execute("select * from claim_donation(%s, %s)", (d, JARO)).fetchone()
    assert claim["reserved_price"] is None


def test_sold_after_confirm(conn):
    d = sale(conn, 80)
    claim = conn.execute("select * from claim_donation(%s, %s)", (d, JARO)).fetchone()
    conn.execute("select * from confirm_pickup(%s, %s)", (claim["id"], "https://example.com/p.jpg"))
    assert row(conn, d)["status"] == "sold"
