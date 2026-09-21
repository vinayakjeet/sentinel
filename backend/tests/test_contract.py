import uuid
from datetime import UTC, datetime

import pytest

from app.core.config import get_settings
from app.core.security import decode_token
from app.schemas.decision import Band, DecisionOutcome, DecisionResponse, GraphSignals, ReasonCode
from app.services.adverse_action import NotAdverseAction, build_notice

# DESIGN §10: every route must be in the frozen OpenAPI with its method.
CONTRACT = {
    ("post", "/api/v1/auth/login"),
    ("post", "/api/v1/decisions/application"),
    ("get", "/api/v1/decisions/{decision_id}"),
    ("get", "/api/v1/decisions"),
    ("get", "/api/v1/decisions/{decision_id}/adverse-action"),
    ("get", "/api/v1/entities/{application_id}/graph"),
    ("get", "/api/v1/cases/{decision_id}/similar"),
    ("get", "/api/v1/stream"),
    ("post", "/api/v1/stream/switch"),
    ("post", "/api/v1/stream/start"),
    ("post", "/api/v1/stream/stop"),
    ("get", "/api/v1/metrics"),
    ("get", "/api/v1/metrics/drift"),
    ("post", "/api/v1/copilot/ask"),
    ("get", "/health"),
    ("get", "/ready"),
}


def test_openapi_contains_every_design_route(client):
    spec = client.get("/openapi.json").json()
    present = {(m, p) for p, ops in spec["paths"].items() for m in ops}
    assert CONTRACT <= present, CONTRACT - present


def test_every_json_route_declares_a_response_model(client):
    spec = client.get("/openapi.json").json()
    for path, ops in spec["paths"].items():
        for method, op in ops.items():
            ok = op["responses"].get("200") or op["responses"].get("201")
            content = ok["content"]
            schema = next(iter(content.values()))["schema"]
            assert schema, f"{method.upper()} {path} has no response schema"


def test_login_issues_jwt_with_role(client):
    s = get_settings()
    r = client.post(
        "/api/v1/auth/login",
        json={"username": s.demo_admin_username, "password": s.demo_admin_password.get_secret_value()},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["role"] == "admin" and body["token_type"] == "bearer"
    assert decode_token(body["access_token"]).username == s.demo_admin_username


def test_login_wrong_password_401(client):
    s = get_settings()
    r = client.post("/api/v1/auth/login", json={"username": s.demo_analyst_username, "password": "nope"})
    assert r.status_code == 401


def _decision(band: Band, n_reasons: int) -> DecisionResponse:
    return DecisionResponse(
        decision_id=uuid.uuid4(),
        application_id=uuid.uuid4(),
        score=900,
        band=band,
        decision=DecisionOutcome.DECLINED,
        reason_codes=[
            ReasonCode(
                feature=f"raw_feature_{i}", reason=f"reason {i}", ecoa_category=f"cat {i}", contribution=float(i)
            )
            for i in range(n_reasons)
        ],
        graph_signals=GraphSignals(),
        graph_uplift=0.0,
        model_version="t",
        latency_ms=1.0,
        created_at=datetime.now(UTC),
    )


def test_adverse_action_top4_reasons_applicant_facing_only():
    notice = build_notice(_decision(Band.DECLINE, 5))
    assert [r.reason for r in notice.principal_reasons] == ["reason 4", "reason 3", "reason 2", "reason 1"]
    dumped = notice.model_dump_json()
    assert "raw_feature" not in dumped and "contribution" not in dumped and "score" not in dumped


def test_adverse_action_only_for_declines(client, payload):
    with pytest.raises(NotAdverseAction):
        build_notice(_decision(Band.REVIEW, 4))
    d = client.post("/api/v1/decisions/application", json=payload).json()
    assert client.get(f"/api/v1/decisions/{d['decision_id']}/adverse-action").status_code == 409
