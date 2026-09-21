"""All SQL for the semantic layer (repositories own SQL, per CLAUDE.md conventions)."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session


def _to_pgvector(embedding: Sequence[float]) -> str:
    return "[" + ",".join(format(float(v), ".8f") for v in embedding) + "]"


def upsert_embedding(
    db: Session, decision_id: uuid.UUID, embedding: Sequence[float], metadata: dict[str, Any]
) -> None:
    """Idempotent, so a retried background task or a re-run backfill cannot create duplicates."""
    import json

    db.execute(
        text(
            """
            INSERT INTO case_embeddings (decision_id, embedding, metadata)
            VALUES (:decision_id, CAST(:embedding AS vector), CAST(:metadata AS jsonb))
            ON CONFLICT (decision_id) DO UPDATE
                SET embedding = EXCLUDED.embedding,
                    metadata  = EXCLUDED.metadata
            """
        ),
        {
            "decision_id": str(decision_id),
            "embedding": _to_pgvector(embedding),
            "metadata": json.dumps(metadata),
        },
    )


def find_similar(db: Session, decision_id: uuid.UUID, k: int = 5) -> list[dict[str, Any]]:
    """k nearest case narratives by cosine distance, excluding the case itself.

    The ORDER BY is on the raw `<=>` operator so the HNSW index is used; similarity is reported as
    1 - distance so that higher is more similar, matching SimilarCase.similarity.
    """
    rows = db.execute(
        text(
            """
            WITH target AS (
                SELECT embedding FROM case_embeddings WHERE decision_id = :decision_id
            )
            SELECT  d.id              AS decision_id,
                    d.application_id  AS application_id,
                    d.score           AS score,
                    d.band            AS band,
                    d.reason_codes    AS reason_codes,
                    d.created_at      AS created_at,
                    1 - (ce.embedding <=> (SELECT embedding FROM target)) AS similarity
            FROM case_embeddings ce
            JOIN decisions d ON d.id = ce.decision_id
            WHERE ce.decision_id <> :decision_id
              AND EXISTS (SELECT 1 FROM target)
            ORDER BY ce.embedding <=> (SELECT embedding FROM target)
            LIMIT :k
            """
        ),
        {"decision_id": str(decision_id), "k": k},
    ).mappings().all()
    return [dict(r) for r in rows]


def has_embedding(db: Session, decision_id: uuid.UUID) -> bool:
    return db.execute(
        text("SELECT 1 FROM case_embeddings WHERE decision_id = :decision_id"),
        {"decision_id": str(decision_id)},
    ).first() is not None


def decisions_missing_embeddings(db: Session, limit: int = 1000) -> list[dict[str, Any]]:
    """Backfill worklist: decisions with no row in case_embeddings yet."""
    rows = db.execute(
        text(
            """
            SELECT d.id AS decision_id, d.band, d.decision, d.reason_codes,
                   d.graph_signals, d.graph_uplift
            FROM decisions d
            LEFT JOIN case_embeddings ce ON ce.decision_id = d.id
            WHERE ce.decision_id IS NULL
            ORDER BY d.created_at
            LIMIT :limit
            """
        ),
        {"limit": limit},
    ).mappings().all()
    return [dict(r) for r in rows]


def load_decision_for_embedding(db: Session, decision_id: uuid.UUID) -> dict[str, Any] | None:
    row = db.execute(
        text(
            """
            SELECT id AS decision_id, band, decision, reason_codes, graph_signals, graph_uplift
            FROM decisions WHERE id = :decision_id
            """
        ),
        {"decision_id": str(decision_id)},
    ).mappings().first()
    return dict(row) if row else None


def count_embeddings(db: Session) -> int:
    return int(db.execute(text("SELECT count(*) FROM case_embeddings")).scalar_one())
