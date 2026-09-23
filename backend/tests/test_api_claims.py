"""POST /api/claims against the real DB; Telegram sending is mocked."""
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app import db
from app.main import app
from tests.conftest import CITY_PROPER, JARO, LA_PAZ, insert_donation

client = TestClient(app)  # no context manager: the bot doesn't start in tests


@pytest.fixture
def donation():
    """A committed listing next to the Jaro pantry (2 km radius); removed afterwards."""
    conn = db.connect()
    donation_id = insert_donation(conn, food_type="API test lumpia", quantity="20 pcs")
    conn.commit()
    yield str(donation_id)
    conn.execute("delete from claims where donation_id = %s", (donation_id,))
    conn.execute("delete from donations where id = %s", (donation_id,))
    conn.commit()
    conn.close()


@patch("app.routes.telegram.send_message", new_callable=AsyncMock)
def test_claim_succeeds_and_notifies_donor(send, donation):
    res = client.post("/api/claims", json={"donation_id": donation, "recipient_id": JARO})
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["donation_id"] == donation and body["recipient_id"] == JARO
    assert body["distance_m"] < 200

    with db.connect() as conn:
        assert conn.execute("select status from donations where id = %s", (donation,)).fetchone()["status"] == "claimed"

    send.assert_awaited_once()
    text = send.await_args.args[1]
    assert "Bayanihan Pantry Jaro" in text and "API test lumpia" in text


@patch("app.routes.telegram.send_message", new_callable=AsyncMock)
def test_second_claim_gets_409(send, donation):
    assert client.post("/api/claims", json={"donation_id": donation, "recipient_id": JARO}).status_code == 201
    res = client.post("/api/claims", json={"donation_id": donation, "recipient_id": LA_PAZ})
    assert res.status_code == 409
    assert "claimed" in res.json()["detail"]
    assert send.await_count == 1  # only the winning claim notifies


@patch("app.routes.telegram.send_message", new_callable=AsyncMock)
def test_out_of_range_claim_gets_409(send, donation):
    res = client.post("/api/claims", json={"donation_id": donation, "recipient_id": CITY_PROPER})
    assert res.status_code == 409
    send.assert_not_awaited()


def test_invalid_ids_get_422():
    res = client.post("/api/claims", json={"donation_id": "not-a-uuid", "recipient_id": JARO})
    assert res.status_code == 422


def test_cors_allows_frontend():
    res = client.options(
        "/api/claims",
        headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "POST",
                 "Access-Control-Request-Headers": "content-type"},
    )
    assert res.status_code == 200
    assert res.headers["access-control-allow-origin"] == "http://localhost:5173"


@pytest.fixture
def sale_listing():
    conn = db.connect()
    donation_id = insert_donation(conn, food_type="Sale test pandesal", quantity="40 pcs",
                                  listing_type="sale", original_price=100, current_price=100)
    # halfway through its price window (whatever the configured window is) -> live price ~P50
    conn.execute("update donations set radius_widened_at = now() - make_interval(secs => "
                 "(select value from app_config where key = 'widen_after_minutes') * 30) where id = %s",
                 (donation_id,))
    conn.commit()
    yield str(donation_id)
    conn.execute("delete from claims where donation_id = %s", (donation_id,))
    conn.execute("delete from donations where id = %s", (donation_id,))
    conn.commit()
    conn.close()


@patch("app.routes.telegram.send_message", new_callable=AsyncMock)
def test_reserving_sale_locks_price_and_tells_donor(send, sale_listing):
    res = client.post("/api/claims", json={"donation_id": sale_listing, "recipient_id": JARO})
    assert res.status_code == 201, res.text
    price = float(res.json()["reserved_price"])
    assert 48 <= price <= 50  # live price at reserve time, not the stale stored P100
    text = send.await_args.args[1]
    assert "Reserved" in text and f"₱{price:g}" in text and "pay you" in text
