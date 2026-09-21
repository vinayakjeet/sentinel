import re
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from jose import jwt

from app.core.config import get_settings

PUBLIC = {("get", "/health"), ("get", "/ready"), ("post", "/api/v1/auth/login")}
ADMIN_ONLY = [
    ("post", "/api/v1/stream/start"),
    ("post", "/api/v1/stream/stop"),
    ("post", "/api/v1/stream/switch?source=base"),
    ("post", "/api/v1/metrics/drift/reset"),
]


def _routes(client):
    spec = client.get("/openapi.json").json()
    for path, ops in spec["paths"].items():
        for method in ops:
            yield method, path


def test_every_non_public_route_requires_a_token(client, anon):
    checked = 0
    for method, path in _routes(client):
        if (method, path) in PUBLIC:
            continue
        concrete = re.sub(r"\{[^}]+\}", str(uuid.uuid4()), path)
        r = anon.request(method, concrete, json={})
        assert r.status_code == 401, f"{method.upper()} {path} -> {r.status_code}"
        assert r.headers.get("www-authenticate") == "Bearer"
        checked += 1
    assert checked >= 15


def test_public_routes_need_no_token(anon):
    assert anon.get("/health").status_code == 200
    assert anon.get("/ready").status_code == 200
    assert anon.get("/docs").status_code == 200


@pytest.mark.parametrize("token", ["garbage", "a.b.c"])
def test_invalid_token_401(anon, token):
    r = anon.get("/api/v1/decisions", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401 and r.json()["detail"] == "invalid or expired token"


def test_expired_token_401(anon):
    s = get_settings()
    past = datetime.now(UTC) - timedelta(hours=2)
    token = jwt.encode(
        {"sub": "admin", "role": "admin", "iat": past, "exp": past + timedelta(minutes=60)},
        s.jwt_secret.get_secret_value(),
        algorithm=s.jwt_algorithm,
    )
    assert anon.get("/api/v1/decisions", headers={"Authorization": f"Bearer {token}"}).status_code == 401


def test_token_signed_with_another_key_401(anon):
    forged = jwt.encode({"sub": "admin", "role": "admin", "exp": datetime.now(UTC) + timedelta(hours=1)},
                        "not-the-secret", algorithm="HS256")
    assert anon.get("/api/v1/decisions", headers={"Authorization": f"Bearer {forged}"}).status_code == 401


def test_sse_query_token_is_validated(anon):
    assert anon.get("/api/v1/stream?token=garbage").status_code == 401


@pytest.mark.parametrize("method, path", ADMIN_ONLY)
def test_analyst_forbidden_on_admin_routes(analyst, method, path):
    r = analyst.request(method, path)
    assert r.status_code == 403 and r.json()["detail"] == "admin role required"


def test_analyst_can_read(analyst):
    assert analyst.get("/api/v1/decisions").status_code == 200
    assert analyst.get("/api/v1/metrics/drift").status_code == 200


def test_login_rate_limited_429(anon):
    s = get_settings()
    limit = int(s.rate_limit_login.split("/")[0])
    codes = [
        anon.post("/api/v1/auth/login", json={"username": "nobody", "password": "x"}).status_code
        for _ in range(limit + 2)
    ]
    assert codes[:limit] == [401] * limit and codes[-1] == 429
    body = anon.post("/api/v1/auth/login", json={"username": "nobody", "password": "x"}).json()
    assert body["detail"].startswith("rate limit exceeded") and "request_id" in body


def test_oversized_body_413(client, payload):
    payload["address"] = "x" * (get_settings().max_body_bytes + 1)
    assert client.post("/api/v1/decisions/application", json=payload).status_code == 413


def test_unhandled_error_500_has_no_stack_trace(client):
    from app.main import app

    def boom():
        raise RuntimeError("secret internal detail")

    app.add_api_route("/__test_boom", boom, include_in_schema=False)
    with TestClient(app, raise_server_exceptions=False) as c:
        r = c.get("/__test_boom")
    assert r.status_code == 500
    assert r.json()["detail"] == "internal server error" and r.json()["request_id"]
    assert "secret internal detail" not in r.text and "Traceback" not in r.text


def test_cors_allowlist(anon):
    ok = anon.options(
        "/api/v1/decisions",
        headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET"},
    )
    assert ok.headers.get("access-control-allow-origin") == "http://localhost:5173"
    bad = anon.options(
        "/api/v1/decisions",
        headers={"Origin": "http://evil.example", "Access-Control-Request-Method": "GET"},
    )
    assert "access-control-allow-origin" not in bad.headers


def test_validation_error_never_echoes_password(anon):
    secret = "S3cret-" + "p" * 200
    r = anon.post("/api/v1/auth/login", json={"username": "admin", "password": secret})
    assert r.status_code == 422 and secret not in r.text and "p" * 50 not in r.text
