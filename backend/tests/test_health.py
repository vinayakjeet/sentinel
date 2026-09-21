from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_ok_and_request_id_echoed():
    r = client.get("/health", headers={"X-Request-ID": "abc-123"})
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}
    assert r.headers["x-request-id"] == "abc-123"


def test_ready_checks_database():
    r = client.get("/ready")
    assert r.status_code == 200
    assert r.json() == {"status": "ready", "database": "ok"}
