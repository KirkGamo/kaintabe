from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_reaches_db_with_extensions():
    res = client.get("/health")
    assert res.status_code == 200
    body = res.json()
    assert body["db"] == "ok", body
    assert "postgis" in body["extensions"]
    assert "pg_cron" in body["extensions"]
