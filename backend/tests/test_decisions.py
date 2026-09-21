import uuid

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models import Application, AuditLog, Decision

URL = "/api/v1/decisions/application"


def test_decision_is_persisted_with_audit(client, payload):
    r = client.post(URL, json=payload, headers={"X-Request-ID": "test-persist-1"})
    assert r.status_code == 201, r.text
    body = r.json()
    assert set(body) >= {
        "decision_id", "application_id", "score", "band", "decision", "reason_codes",
        "graph_signals", "graph_uplift", "model_version", "latency_ms", "created_at",
    }
    assert 0 <= body["score"] <= 1000
    assert body["latency_ms"] > 0

    with SessionLocal() as db:
        d = db.get(Decision, uuid.UUID(body["decision_id"]))
        assert d is not None
        assert d.request_id == "test-persist-1"
        assert d.score == body["score"] and d.band == body["band"]
        assert d.thresholds == {"step_up": 300, "review": 650, "decline": 850}
        app_row = db.get(Application, uuid.UUID(body["application_id"]))
        # Identifiers are never stored in clear on the application row.
        assert "email" not in app_row.features and "applicant_name" not in app_row.features
        assert app_row.fraud_bool is None
        audit = db.scalars(select(AuditLog).where(AuditLog.resource_id == body["decision_id"])).one()
        assert audit.action == "decision.created" and audit.request_id == "test-persist-1"

    got = client.get(f"/api/v1/decisions/{body['decision_id']}")
    assert got.status_code == 200
    assert got.json() == body


def test_fraud_label_only_honoured_for_history(client, payload):
    payload["fraud_bool"] = 1
    live = client.post(URL, json=payload).json()
    payload["history"] = True
    hist = client.post(URL, json=payload).json()
    with SessionLocal() as db:
        assert db.get(Application, uuid.UUID(live["application_id"])).fraud_bool is None
        assert db.get(Application, uuid.UUID(hist["application_id"])).fraud_bool == 1


def test_get_unknown_decision_404(client):
    r = client.get("/api/v1/decisions/00000000-0000-0000-0000-000000000000")
    assert r.status_code == 404


def test_list_filters_by_band(client, payload):
    band = client.post(URL, json=payload).json()["band"]
    r = client.get("/api/v1/decisions", params={"band": band, "limit": 5})
    assert r.status_code == 200
    body = r.json()
    assert body["total"] >= 1 and len(body["items"]) <= 5
    assert all(item["band"] == band for item in body["items"])
    assert client.get("/api/v1/decisions", params={"band": "MAYBE"}).status_code == 422
