"""POST /api/claims/{id}/confirm: only whoever claimed it (org or individual, by signed initData) can confirm."""
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app import db
from app.main import app
from tests.conftest import insert_donation

client = TestClient(app)
JPEG = b"\xff\xd8\xff\xe0fake-jpeg"
PHOTO_URL = "https://example.com/pickup.jpg"


@pytest.fixture
def claim(api_orgs):
    """A committed listing (2 kg) claimed by the test Jaro org; removed afterwards."""
    ids, headers = api_orgs
    conn = db.connect()
    donation_id = insert_donation(conn, food_type="Confirm test puto", quantity="30 pcs", est_kg=2)
    c = conn.execute("select * from claim_donation(%s, %s)", (donation_id, ids["jaro"])).fetchone()
    conn.commit()
    yield str(c["id"]), str(donation_id), headers
    conn.execute("delete from claims where donation_id = %s", (donation_id,))
    conn.execute("delete from donations where id = %s", (donation_id,))
    conn.commit()
    conn.close()


def confirm(claim_id, headers, photo=JPEG, content_type="image/jpeg"):
    return client.post(f"/api/claims/{claim_id}/confirm", headers=headers,
                       files={"photo": ("pickup.jpg", photo, content_type)})


@patch("app.routes.telegram.send_photo", new_callable=AsyncMock)
@patch("app.routes.storage.upload_photo", new_callable=AsyncMock, return_value=PHOTO_URL)
def test_confirm_completes_and_thanks_donor(upload, send, claim):
    claim_id, donation_id, headers = claim
    res = confirm(claim_id, headers("jaro"))
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
    assert "API Org jaro" in caption and "~2 kg" in caption and "5 meals" in caption


@patch("app.routes.telegram.send_photo", new_callable=AsyncMock)
@patch("app.routes.storage.upload_photo", new_callable=AsyncMock, return_value=PHOTO_URL)
def test_confirm_twice_gets_409(upload, send, claim):
    claim_id, _, headers = claim
    assert confirm(claim_id, headers("jaro")).status_code == 200
    assert confirm(claim_id, headers("jaro")).status_code == 409
    assert upload.await_count == 1 and send.await_count == 1


@patch("app.routes.storage.upload_photo", new_callable=AsyncMock, return_value=PHOTO_URL)
def test_other_org_cannot_confirm(upload, claim):
    claim_id, _, headers = claim
    assert confirm(claim_id, headers("lapaz")).status_code == 403
    upload.assert_not_awaited()


@patch("app.routes.storage.upload_photo", new_callable=AsyncMock, return_value=PHOTO_URL)
def test_confirm_needs_telegram_identity(upload, claim):
    claim_id, _, headers = claim
    assert confirm(claim_id, {}).status_code == 401  # a normal browser can't confirm
    assert confirm(claim_id, headers(tg_id=-219999)).status_code == 403  # Telegram user with no role
    upload.assert_not_awaited()


@patch("app.routes.storage.upload_photo", new_callable=AsyncMock, return_value=PHOTO_URL)
def test_rejects_non_image_and_empty(upload, claim):
    claim_id, _, headers = claim
    assert confirm(claim_id, headers("jaro"), photo=b"hello", content_type="text/plain").status_code == 422
    assert confirm(claim_id, headers("jaro"), photo=b"").status_code == 422
    upload.assert_not_awaited()


def test_unknown_claim_gets_404(api_orgs):
    _, headers = api_orgs
    assert confirm("00000000-0000-0000-0000-000000000000", headers("jaro")).status_code == 404


@patch("app.routes.telegram.send_photo", new_callable=AsyncMock)
@patch("app.routes.storage.upload_photo", new_callable=AsyncMock, return_value=PHOTO_URL)
def test_confirming_sale_marks_sold(upload, send, api_orgs):
    ids, headers = api_orgs
    conn = db.connect()
    donation_id = insert_donation(conn, listing_type="sale", original_price=90, current_price=45, est_kg=1)
    c = conn.execute("select * from claim_donation(%s, %s)", (donation_id, ids["jaro"])).fetchone()
    conn.commit()
    try:
        res = confirm(str(c["id"]), headers("jaro"))
        assert res.status_code == 200 and res.json()["donation_status"] == "sold"
        caption = send.await_args.args[2]
        assert "Sold" in caption and f"₱{float(c['reserved_price']):g}" in caption
    finally:
        conn.execute("delete from claims where donation_id = %s", (donation_id,))
        conn.execute("delete from donations where id = %s", (donation_id,))
        conn.commit()
        conn.close()


def test_meal_wording_singular_and_plural():
    from app.services import notify
    base = {"food_type": "Pizza", "quantity": "2 pcs", "recipient_name": "Kirk", "reserved_price": None}
    assert "≈ 1 meal." in notify.picked_up_text({**base, "est_kg": 0.5})
    assert "≈ 5 meals." in notify.picked_up_text({**base, "est_kg": 2})


@patch("app.routes.telegram.send_photo", new_callable=AsyncMock)
@patch("app.routes.storage.upload_photo", new_callable=AsyncMock, return_value=PHOTO_URL)
def test_individual_confirms_their_flash_pickup(upload, send, api_orgs):
    """Regression: the map showed individuals the confirm button, but the API only accepted orgs (403)."""
    from app.services import repo
    _, headers = api_orgs
    person = repo.upsert_individual(-219101, "Karlo", 10.7260, 122.5585, "api_test_bot")
    other = repo.upsert_individual(-219102, "Someone", 10.7260, 122.5585, "api_test_bot")
    conn = db.connect()
    donation_id = insert_donation(conn, food_type="Confirm test flash", est_kg=2, status="escalated", radius_m=8000)
    c = conn.execute("select * from claim_donation(%s, %s)", (donation_id, person["id"])).fetchone()
    conn.commit()
    try:
        assert confirm(str(c["id"]), headers(tg_id=-219102)).status_code == 403  # not theirs
        upload.assert_not_awaited()
        res = confirm(str(c["id"]), headers(tg_id=-219101))
        assert res.status_code == 200, res.text
        assert res.json()["donation_status"] == "completed"
        assert "Karlo" in send.await_args.args[2]
    finally:
        conn.execute("delete from claims where donation_id = %s", (donation_id,))
        conn.execute("delete from donations where id = %s", (donation_id,))
        conn.execute("delete from recipients where id = any(%s::uuid[])", ([str(person["id"]), str(other["id"])],))
        conn.commit()
        conn.close()
