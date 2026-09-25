"""POST /api/claims: who claims comes from signed Telegram initData (real DB; Telegram sending mocked)."""
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app import db
from app.main import app
from tests.conftest import insert_donation

client = TestClient(app)  # no context manager: the bot doesn't start in tests


@pytest.fixture
def donation():
    """A committed listing next to Jaro (2 km radius); removed afterwards."""
    conn = db.connect()
    donation_id = insert_donation(conn, food_type="API test lumpia", quantity="20 pcs")
    conn.commit()
    yield str(donation_id)
    conn.execute("delete from claims where donation_id = %s", (donation_id,))
    conn.execute("delete from donations where id = %s", (donation_id,))
    conn.commit()
    conn.close()


def claim(donation_id, headers, **extra):
    return client.post("/api/claims", json={"donation_id": donation_id, **extra}, headers=headers)


@patch("app.routes.telegram.send_message", new_callable=AsyncMock)
def test_claim_succeeds_and_notifies_donor(send, donation, api_orgs):
    ids, headers = api_orgs
    res = claim(donation, headers("jaro"))
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["donation_id"] == donation and body["recipient_id"] == ids["jaro"]
    assert body["distance_m"] < 200
    with db.connect() as conn:
        assert conn.execute("select status from donations where id = %s", (donation,)).fetchone()["status"] == "claimed"
    send.assert_awaited_once()
    assert "API Org jaro" in send.await_args.args[1] and "API test lumpia" in send.await_args.args[1]


@patch("app.routes.telegram.send_message", new_callable=AsyncMock)
def test_body_recipient_id_is_ignored(send, donation, api_orgs):
    """Security: naming another org in the body doesn't let you claim as it."""
    ids, headers = api_orgs
    res = claim(donation, headers("jaro"), recipient_id=ids["lapaz"])
    assert res.status_code == 201 and res.json()["recipient_id"] == ids["jaro"]


@patch("app.routes.telegram.send_message", new_callable=AsyncMock)
def test_second_claim_gets_409(send, donation, api_orgs):
    _, headers = api_orgs
    assert claim(donation, headers("jaro")).status_code == 201
    res = claim(donation, headers("lapaz"))
    assert res.status_code == 409 and "claimed" in res.json()["detail"]
    assert send.await_count == 1


@patch("app.routes.telegram.send_message", new_callable=AsyncMock)
def test_out_of_range_claim_gets_409(send, donation, api_orgs):
    _, headers = api_orgs
    assert claim(donation, headers("cityproper")).status_code == 409
    send.assert_not_awaited()


def test_no_or_bad_identity_gets_401(donation, api_orgs):
    ids, headers = api_orgs
    assert client.post("/api/claims", json={"donation_id": donation, "recipient_id": ids["jaro"]}).status_code == 401
    tampered = {"X-Telegram-Init-Data": headers("jaro")["X-Telegram-Init-Data"].replace("Tester", "Mallory")}
    assert claim(donation, tampered).status_code == 401


def test_telegram_user_who_is_not_an_org_gets_403(donation, api_orgs):
    _, headers = api_orgs
    res = claim(donation, headers(tg_id=-219999))
    assert res.status_code == 403 and "partner kitchens" in res.json()["detail"]


@patch("app.routes.telegram.send_message", new_callable=AsyncMock)
def test_individual_claims_only_what_they_were_flash_offered(send, api_orgs):
    """Kitchens get first pick: an individual can claim on the map only food flash-offered to them."""
    from app.services import repo
    _, headers = api_orgs
    person = repo.upsert_individual(-219201, "Karlo", 10.7260, 122.5585, "api_test_bot")
    conn = db.connect()
    offered = insert_donation(conn, food_type="API flash offered", status="escalated", radius_m=8000)
    other = insert_donation(conn, food_type="API flash not offered", status="escalated", radius_m=8000)
    conn.execute("insert into flash_offers (donation_id, recipient_id) values (%s, %s)", (offered, person["id"]))
    conn.commit()
    try:
        assert claim(str(other), headers(tg_id=-219201)).status_code == 403
        res = claim(str(offered), headers(tg_id=-219201))
        assert res.status_code == 201, res.text
        assert res.json()["recipient_id"] == str(person["id"])
        assert "Karlo" in send.await_args.args[1]

        view = client.get("/api/map", headers=headers(tg_id=-219201)).json()
        assert str(offered) in {p["id"] for p in view["my_pickups"]}  # now exact, with directions
        assert str(offered) not in {o["id"] for o in view["flash_offers"]}  # no longer open
    finally:
        conn.execute("delete from claims where donation_id = any(%s::uuid[])", ([str(offered), str(other)],))
        conn.execute("delete from donations where id = any(%s::uuid[])", ([str(offered), str(other)],))
        conn.execute("delete from recipients where id = %s", (person["id"],))
        conn.commit()
        conn.close()


def test_open_flash_offers_listed_for_the_individual(api_orgs):
    from app.services import repo
    _, headers = api_orgs
    person = repo.upsert_individual(-219202, "Ana", 10.7260, 122.5585, "api_test_bot")
    conn = db.connect()
    offered = insert_donation(conn, food_type="API open offer", status="escalated", radius_m=8000)
    conn.execute("insert into flash_offers (donation_id, recipient_id) values (%s, %s)", (offered, person["id"]))
    conn.commit()
    try:
        offers = client.get("/api/map", headers=headers(tg_id=-219202)).json()["flash_offers"]
        mine = [o for o in offers if o["id"] == str(offered)]
        assert len(mine) == 1 and mine[0]["food_type"] == "API open offer" and mine[0]["distance_m"] < 300
        assert "lat" not in mine[0]  # the exact spot comes only after claiming
    finally:
        conn.execute("delete from donations where id = %s", (offered,))
        conn.execute("delete from recipients where id = %s", (person["id"],))
        conn.commit()
        conn.close()


def test_invalid_ids_get_422(api_orgs):
    _, headers = api_orgs
    assert claim("not-a-uuid", headers("jaro")).status_code == 422


def test_cors_allows_frontend_with_identity_header():
    res = client.options(
        "/api/claims",
        headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "POST",
                 "Access-Control-Request-Headers": "content-type,x-telegram-init-data"},
    )
    assert res.status_code == 200
    assert res.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_me_and_config(api_orgs):
    ids, headers = api_orgs
    me = client.get("/api/me", headers=headers("jaro")).json()
    assert me["org"]["id"] == ids["jaro"] and me["org"]["name"] == "API Org jaro"
    assert client.get("/api/me", headers=headers(tg_id=-219999)).json()["org"] is None
    assert client.get("/api/me").status_code == 401
    assert client.get("/api/config").json() == {"bot_username": "api_test_bot"}


@pytest.fixture
def sale_listing():
    conn = db.connect()
    donation_id = insert_donation(conn, food_type="Sale test pandesal", quantity="40 pcs",
                                  listing_type="sale", original_price=100, current_price=100)
    # halfway through its price window (whatever the configured window is) -> live price ~P50
    conn.execute("update donations set radius_widened_at = now() - make_interval(secs => "
                 "(select value from app_config where key = 'sale_window_minutes') * 30) where id = %s",
                 (donation_id,))
    conn.commit()
    yield str(donation_id)
    conn.execute("delete from claims where donation_id = %s", (donation_id,))
    conn.execute("delete from donations where id = %s", (donation_id,))
    conn.commit()
    conn.close()


@patch("app.routes.telegram.send_message", new_callable=AsyncMock)
def test_reserving_sale_locks_price_and_tells_donor(send, sale_listing, api_orgs):
    _, headers = api_orgs
    res = claim(sale_listing, headers("jaro"))
    assert res.status_code == 201, res.text
    price = float(res.json()["reserved_price"])
    assert 48 <= price <= 50  # live price at reserve time, not the stale stored P100
    text = send.await_args.args[1]
    assert "Reserved" in text and f"₱{price:g}" in text and "pay you" in text
