"""POST /api/claims/{id}/confirm against the real DB; storage upload and Telegram are mocked."""
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app import db
from app.main import app
from tests.conftest import JARO, LA_PAZ, insert_donation

client = TestClient(app)
JPEG = b"\xff\xd8\xff\xe0fake-jpeg"
PHOTO_URL = "https://example.com/pickup.jpg"


@pytest.fixture
def claim():
    """A committed listing (2 kg) claimed by Jaro; removed afterwards."""
    conn = db.connect()
    donation_id = insert_donation(conn, food_type="Confirm test puto", quantity="30 pcs", est_kg=2)
    claim = conn.execute("select * from claim_donation(%s, %s)", (donation_id, JARO)).fetchone()
    conn.commit()
    yield str(claim["id"]), str(donation_id)
    conn.execute("delete from claims where donation_id = %s", (donation_id,))
    conn.execute("delete from donations where id = %s", (donation_id,))
    conn.commit()
    conn.close()


def confirm(claim_id, recipient_id=JARO, photo=JPEG, content_type="image/jpeg"):
    return client.post(
        f"/api/claims/{claim_id}/confirm",
        data={"recipient_id": recipient_id},
        files={"photo": ("pickup.jpg", photo, content_type)},
    )


@patch("app.routes.telegram.send_photo", new_callable=AsyncMock)
@patch("app.routes.storage.upload_photo", new_callable=AsyncMock, return_value=PHOTO_URL)
def test_confirm_completes_and_thanks_donor(upload, send, claim):
    claim_id, donation_id = claim
    res = confirm(claim_id)
    assert res.status_code == 200, res.text
    assert res.json()["donation_status"] == "completed"
    assert res.json()["confirmation_photo_url"] == PHOTO_URL

    upload.assert_awaited_once_with("pickup-photos", JPEG, "image/jpeg")
    with db.connect() as conn:
        c = conn.execute("select * from claims where id = %s", (claim_id,)).fetchone()
        d = conn.execute("select status from donations where id = %s", (donation_id,)).fetchone()
    assert c["confirmed_at"] is not None and c["confirmation_photo_url"] == PHOTO_URL
    assert d["status"] == "completed"

    send.assert_awaited_once()
    _, photo_bytes, caption = send.await_args.args
    assert photo_bytes == JPEG  # uploaded directly, not as a URL for Telegram to fetch
    assert "Bayanihan Pantry Jaro" in caption and "~2 kg" in caption and "5 meals" in caption


@patch("app.routes.telegram.send_photo", new_callable=AsyncMock)
@patch("app.routes.storage.upload_photo", new_callable=AsyncMock, return_value=PHOTO_URL)
def test_confirm_twice_gets_409(upload, send, claim):
    claim_id, _ = claim
    assert confirm(claim_id).status_code == 200
    res = confirm(claim_id)
    assert res.status_code == 409
    assert upload.await_count == 1 and send.await_count == 1


@patch("app.routes.storage.upload_photo", new_callable=AsyncMock, return_value=PHOTO_URL)
def test_other_org_cannot_confirm(upload, claim):
    claim_id, _ = claim
    assert confirm(claim_id, recipient_id=LA_PAZ).status_code == 403
    upload.assert_not_awaited()


@patch("app.routes.storage.upload_photo", new_callable=AsyncMock, return_value=PHOTO_URL)
def test_rejects_non_image_and_empty(upload, claim):
    claim_id, _ = claim
    assert confirm(claim_id, photo=b"hello", content_type="text/plain").status_code == 422
    assert confirm(claim_id, photo=b"").status_code == 422
    upload.assert_not_awaited()


def test_unknown_claim_gets_404():
    assert confirm("00000000-0000-0000-0000-000000000000").status_code == 404


@patch("app.routes.telegram.send_photo", new_callable=AsyncMock)
@patch("app.routes.storage.upload_photo", new_callable=AsyncMock, return_value=PHOTO_URL)
def test_confirming_sale_marks_sold(upload, send):
    conn = db.connect()
    donation_id = insert_donation(conn, listing_type="sale", original_price=90, current_price=45, est_kg=1)
    claim = conn.execute("select * from claim_donation(%s, %s)", (donation_id, JARO)).fetchone()
    conn.commit()
    try:
        res = confirm(str(claim["id"]))
        assert res.status_code == 200 and res.json()["donation_status"] == "sold"
        caption = send.await_args.args[2]
        assert "Sold" in caption and "₱45" in caption
    finally:
        conn.execute("delete from claims where donation_id = %s", (donation_id,))
        conn.execute("delete from donations where id = %s", (donation_id,))
        conn.commit()
        conn.close()
