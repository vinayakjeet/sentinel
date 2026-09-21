def test_health_ok_and_request_id_echoed(client):
    r = client.get("/health", headers={"X-Request-ID": "abc-123"})
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}
    assert r.headers["x-request-id"] == "abc-123"


def test_ready_checks_database(client):
    r = client.get("/ready")
    assert r.status_code == 200
    assert r.json() == {"status": "ready", "database": "ok"}
