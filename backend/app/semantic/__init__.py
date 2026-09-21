"""Semantic case-similarity layer (DESIGN §8).

Vector similarity finds cases that LOOK alike; the entity graph finds cases that are CONNECTED.
The analyst console shows both, because they answer different questions.

Lane A wiring — two lines in app/api/v1/router.py, replacing the contract stub:

    from app.semantic.router import router as cases_router
    api_router.include_router(cases_router)

plus, in app/api/v1/decisions.py after the decision is persisted:

    background_tasks.add_task(embed_decision, decision.id)

and one line in alembic/env.py so autogenerate does not try to drop case_embeddings:

    from app.semantic import models as _semantic_models  # noqa: F401
"""

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover
    from app.semantic.service import embed_decision, embed_decision_sync

__all__ = ["embed_decision", "embed_decision_sync"]


def __getattr__(name: str) -> Any:
    """Lazy re-export.

    app.semantic.service imports app.db.session, which builds a SQLAlchemy engine at module
    import time. Re-exporting eagerly would mean that importing a leaf module such as
    app.semantic.narrative — which touches no database at all — opens a connection pool. Keeping
    it lazy lets the narrative and embedder be unit-tested without a database.
    """
    if name in __all__:
        from app.semantic import service

        return getattr(service, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
