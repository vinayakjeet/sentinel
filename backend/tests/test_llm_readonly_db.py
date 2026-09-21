"""The database itself refuses writes from the copilot (CLAUDE.md invariant 1, barrier 3).

app/llm/tools.py runs every tool inside a Postgres `SET TRANSACTION READ ONLY` transaction that
is always rolled back. The structural guarantees are tested without a database in
test_llm_guardrails.py; this asserts the one that only a real Postgres can prove.

Runs inside the api container / CI, where conftest has migrated a test database.
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import InternalError, ProgrammingError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.llm import tools


def test_read_only_session_rejects_a_write():
    """A write inside a copilot session must be refused by Postgres, not merely by our code."""
    with pytest.raises((InternalError, ProgrammingError)) as exc:
        with tools.read_only_session() as db:
            db.execute(text("CREATE TEMP TABLE copilot_should_not_be_able_to_do_this (x int)"))
    assert "read-only" in str(exc.value).lower()


def test_read_only_session_still_allows_reads():
    with tools.read_only_session() as db:
        assert db.execute(text("SELECT count(*) FROM decisions")).scalar_one() >= 0


def test_copilot_tools_leave_no_trace():
    """Running every tool must not change the decision count."""
    with tools.read_only_session() as db:
        before = db.execute(text("SELECT count(*) FROM decisions")).scalar_one()

    unknown = uuid.uuid4()
    assert tools.call("get_decision", decision_id=unknown) is None
    assert tools.call("get_entity_graph", application_id=unknown)["n_entities"] == 0
    assert tools.call("find_similar_cases", decision_id=unknown) == []

    with tools.read_only_session() as db:
        after = db.execute(text("SELECT count(*) FROM decisions")).scalar_one()
    assert before == after
