"""impact_summary(): totals move exactly with confirmed pickups (rolled back), and the browser key can call it."""
import httpx

from tests.conftest import JARO, insert_donation


def summary(conn):
    return conn.execute("select impact_summary() s").fetchone()["s"]


def pick_up(conn, **kw):
    d = insert_donation(conn, **kw)
    claim = conn.execute("select * from claim_donation(%s, %s)", (d, JARO)).fetchone()
    conn.execute("select * from confirm_pickup(%s, %s)", (claim["id"], "https://example.com/p.jpg"))
    return d


def test_confirmed_pickups_add_to_totals(conn):
    before = summary(conn)
    pick_up(conn, est_kg=4, food_type="Impact test adobo")
    pick_up(conn, est_kg=2, listing_type="sale", original_price=80, current_price=80)
    after = summary(conn)

    assert float(after["kg_rescued"]) - float(before["kg_rescued"]) == 6
    assert float(after["kg_donated"]) - float(before["kg_donated"]) == 4
    assert float(after["kg_sold"]) - float(before["kg_sold"]) == 2
    assert after["pickups"] - before["pickups"] == 2
    assert float(after["co2e_kg"]) - float(before["co2e_kg"]) == 15  # 6 kg x 2.5
    assert float(after["pesos_to_donors"]) > float(before["pesos_to_donors"])
    assert float(after["daily"][-1]["kg"]) - float(before["daily"][-1]["kg"]) == 6  # counted today (Manila)
    assert after["recent"][0]["listing_type"] in ("donation", "sale")


def test_unconfirmed_claims_do_not_count(conn):
    before = summary(conn)
    d = insert_donation(conn, est_kg=5)
    conn.execute("select * from claim_donation(%s, %s)", (d, JARO))
    assert float(summary(conn)["kg_rescued"]) == float(before["kg_rescued"])


def test_daily_has_seven_days(conn):
    daily = summary(conn)["daily"]
    assert len(daily) == 7 and daily == sorted(daily, key=lambda x: x["day"])


def test_browser_key_can_read_impact(frontend_env):
    base = frontend_env["VITE_SUPABASE_URL"].rstrip("/") + "/rest/v1"
    key = frontend_env["VITE_SUPABASE_ANON_KEY"]
    r = httpx.post(f"{base}/rpc/impact_summary", headers={"apikey": key, "Authorization": f"Bearer {key}"}, json={})
    assert r.status_code == 200 and "kg_rescued" in r.json()
