"""Read-only tool registry for the copilot (DESIGN §9, CLAUDE.md invariant 1).

Three tools, all reads: get_decision, get_entity_graph, find_similar_cases.

The registry is the first of the four barriers between the LLM and the decision record:

* `register` raises if a tool is not declared read-only, so a writable tool cannot be added by
  accident — the guarantee lives in code, not in a convention.
* `call` looks the name up in the registry and refuses anything else, so a model that invents a
  tool name gets an error, not an execution.
* `read_only_session` opens a Postgres `SET TRANSACTION READ ONLY` transaction and always rolls
  back, so even a tool that tried to write would be refused by the database.
"""

from __future__ import annotations

import logging
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Callable, Iterator

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


class ToolError(RuntimeError):
    """Raised when a tool is unknown, not read-only, or fails."""


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    fn: Callable[..., Any]
    read_only: bool = True


_REGISTRY: dict[str, Tool] = {}


def register(tool: Tool) -> Tool:
    if not tool.read_only:
        raise ToolError(
            f"refusing to register non-read-only tool {tool.name!r}: the copilot has no write path "
            "to a score or decision (CLAUDE.md invariant 1)"
        )
    if tool.name in _REGISTRY:
        raise ToolError(f"tool {tool.name!r} is already registered")
    _REGISTRY[tool.name] = tool
    return tool


def registry() -> dict[str, Tool]:
    return dict(_REGISTRY)


def tool_names() -> list[str]:
    return sorted(_REGISTRY)


@contextmanager
def read_only_session() -> Iterator[Session]:
    """A session whose transaction Postgres itself will not let anything write to.

    SessionLocal is imported here rather than at module scope because app.db.session builds a
    SQLAlchemy engine on import, which needs database settings. Keeping it local means the
    guardrails, the registry and the service can all be unit-tested with no database configured
    at all — and the tests that assert invariant 1 are exactly the ones that must not be
    skippable for want of a Postgres.
    """
    from app.db.session import SessionLocal

    db = SessionLocal()
    try:
        db.execute(text("SET TRANSACTION READ ONLY"))
        yield db
    finally:
        # Always roll back. Nothing the copilot does is ever committed.
        db.rollback()
        db.close()


def call(name: str, **kwargs: Any) -> Any:
    """Execute a registered tool. Unknown names are refused rather than guessed at."""
    tool = _REGISTRY.get(name)
    if tool is None:
        raise ToolError(f"unknown tool {name!r}; available: {tool_names()}")
    if not tool.read_only:  # pragma: no cover - register() makes this unreachable
        raise ToolError(f"tool {name!r} is not read-only")
    return tool.fn(**kwargs)


# --------------------------------------------------------------------------------------------
# the three tools
# --------------------------------------------------------------------------------------------
def get_decision(decision_id: uuid.UUID) -> dict[str, Any] | None:
    """The decision record: score, band, outcome, reason codes, graph signals."""
    with read_only_session() as db:
        row = db.execute(
            text(
                """
                SELECT d.id, d.application_id, d.score, d.band, d.decision, d.reason_codes,
                       d.graph_signals, d.graph_uplift, d.model_version, d.created_at
                FROM decisions d
                WHERE d.id = :decision_id
                """
            ),
            {"decision_id": str(decision_id)},
        ).mappings().first()
        return dict(row) if row else None


def get_entity_graph(application_id: uuid.UUID, limit: int = 50) -> dict[str, Any]:
    """Entities this application shares with others — the linkage view, not the lookalike view."""
    with read_only_session() as db:
        rows = db.execute(
            text(
                """
                SELECT e.type, e.value_hash, e.fraud_flag,
                       (SELECT count(*) FROM entity_links l2 WHERE l2.entity_id = e.id) AS shared_by
                FROM entity_links l
                JOIN entities e ON e.id = l.entity_id
                WHERE l.application_id = :application_id
                ORDER BY shared_by DESC
                LIMIT :limit
                """
            ),
            {"application_id": str(application_id), "limit": limit},
        ).mappings().all()
        entities = [dict(r) for r in rows]
        return {
            "entities": entities,
            "n_entities": len(entities),
            "n_shared": sum(1 for e in entities if (e.get("shared_by") or 0) > 1),
            "known_fraud_entities": sum(1 for e in entities if e.get("fraud_flag")),
        }


def find_similar_cases(decision_id: uuid.UUID, k: int = 3) -> list[dict[str, Any]]:
    """Nearest past case narratives, via the semantic layer (DESIGN §8)."""
    from app.semantic import repository as semantic_repo

    with read_only_session() as db:
        if not semantic_repo.has_embedding(db, decision_id):
            return []
        return [
            {
                "decision_id": str(r["decision_id"]),
                "similarity": round(float(r["similarity"]), 4),
                "score": int(r["score"]),
                "band": r["band"],
            }
            for r in semantic_repo.find_similar(db, decision_id, k)
        ]


register(Tool("get_decision", "Fetch a decision: score, band, outcome, reason codes, graph signals.", get_decision))
register(Tool("get_entity_graph", "Entities this application shares with other applications.", get_entity_graph))
register(Tool("find_similar_cases", "Past cases whose narrative resembles this one.", find_similar_cases))
