"""Tests run inside the api container against a separate `sentinel_test` database (migrated to head)."""

import json
import os
from pathlib import Path

os.environ["POSTGRES_DB"] = "sentinel_test"  # must precede any app import (settings are cached)

import psycopg  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from app.core.config import get_settings  # noqa: E402

BACKEND = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).parent / "fixtures"


def _create_test_db() -> None:
    s = get_settings()
    with psycopg.connect(
        host=s.postgres_host,
        port=s.postgres_port,
        user=s.postgres_user,
        password=s.postgres_password.get_secret_value(),
        dbname="postgres",
        autocommit=True,
    ) as conn:
        exists = conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (s.postgres_db,)).fetchone()
        if not exists:
            conn.execute(f'CREATE DATABASE "{s.postgres_db}"')


@pytest.fixture(scope="session", autouse=True)
def _migrated_db():
    _create_test_db()
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "alembic"))
    command.upgrade(cfg, "head")
    from app.db.session import engine

    with engine.begin() as conn:
        conn.execute(text("TRUNCATE applications, decisions, entities, entity_links, drift_events, audit_log CASCADE"))
    yield


def _token(role: str) -> str:
    from app.core.security import Principal, create_access_token

    s = get_settings()
    username = s.demo_admin_username if role == "admin" else s.demo_analyst_username
    return create_access_token(Principal(username=username, role=role))[0]


@pytest.fixture(scope="session")
def client():
    """Authenticated as admin (most tests exercise behaviour, not auth)."""
    from app.main import app

    with TestClient(app, headers={"Authorization": f"Bearer {_token('admin')}"}) as c:  # runs the lifespan
        yield c


@pytest.fixture(scope="session")
def anon(client):
    from app.main import app

    return TestClient(app)  # lifespan already ran via `client`


@pytest.fixture(scope="session")
def analyst(client):
    from app.main import app

    return TestClient(app, headers={"Authorization": f"Bearer {_token('analyst')}"})


@pytest.fixture(autouse=True)
def _fresh_rate_limits():
    from app.core.limits import limiter

    limiter.reset()
    yield


@pytest.fixture
def payload() -> dict:
    return json.loads((FIXTURES / "application.json").read_text())
