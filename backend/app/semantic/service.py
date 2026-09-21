"""Embedding service — the background task Lane A calls after a decision is persisted."""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.semantic import repository
from app.semantic.embedder import get_embedder
from app.semantic.narrative import build_narrative, narrative_metadata

logger = logging.getLogger(__name__)


def embed_decision_sync(db: Session, decision_id: uuid.UUID) -> bool:
    """Embed one persisted decision. Returns False if the decision no longer exists."""
    row = repository.load_decision_for_embedding(db, decision_id)
    if row is None:
        logger.warning("cannot embed unknown decision", extra={"decision_id": str(decision_id)})
        return False

    narrative = build_narrative(
        band=row["band"],
        decision=row.get("decision"),
        reason_codes=row.get("reason_codes"),
        graph_signals=row.get("graph_signals"),
        graph_uplift=row.get("graph_uplift"),
    )
    metadata: dict[str, Any] = narrative_metadata(
        band=row["band"],
        reason_codes=row.get("reason_codes"),
        graph_signals=row.get("graph_signals"),
    )
    metadata["narrative"] = narrative

    embedding = get_embedder().encode(narrative)
    repository.upsert_embedding(db, decision_id, embedding, metadata)
    db.commit()
    return True


def embed_decision(decision_id: uuid.UUID) -> None:
    """FastAPI BackgroundTasks entry point.

    Owns its own session, because the request's session is closed by the time this runs. Never
    raises: a failed embedding must not surface as a failed scoring request, since similarity is
    an analyst convenience and scoring is the product.
    """
    db = SessionLocal()
    try:
        embed_decision_sync(db, decision_id)
    except Exception:
        db.rollback()
        logger.exception("background embedding failed", extra={"decision_id": str(decision_id)})
    finally:
        db.close()
