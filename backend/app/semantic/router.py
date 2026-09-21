"""GET /cases/{decision_id}/similar (DESIGN §8, §10).

Implements the contract in app/schemas/cases.py, which Lane A owns — the stub router in
app/api/v1/_contract_stubs.py is replaced by this one, keeping identical paths and models.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.security import Principal, get_current_user
from app.db.session import get_db
from app.schemas.cases import SimilarCase, SimilarCasesResponse
from app.schemas.common import ErrorResponse
from app.semantic import repository

router = APIRouter(prefix="/cases", tags=["cases"])

# Matches the frozen contract in app/api/v1/_contract_stubs.py exactly. Do not widen: the stub
# this router replaces advertises le=20 in docs/openapi.json.
MAX_K = 20


def _top_reason_texts(reason_codes) -> list[str]:
    out: list[str] = []
    for entry in reason_codes or []:
        if isinstance(entry, dict):
            text = entry.get("reason") or entry.get("feature")
            if text:
                out.append(str(text))
    return out[:4]


@router.get(
    "/{decision_id}/similar",
    response_model=SimilarCasesResponse,
    responses={404: {"model": ErrorResponse}},
    summary="Nearest past cases by narrative embedding",
)
def get_similar_cases(
    decision_id: uuid.UUID,
    k: int = Query(5, ge=1, le=MAX_K),
    db: Session = Depends(get_db),
    user: Principal = Depends(get_current_user),
) -> SimilarCasesResponse:
    """Nearest case narratives by cosine similarity over the HNSW index.

    Similarity answers "does this look like something I have seen before"; the entity graph
    answers "is this connected to something I have seen before". They are different questions and
    the console shows both.
    """
    if not repository.has_embedding(db, decision_id):
        # Distinguish "no such decision" from "not embedded yet": the embedding is written by a
        # background task, so a very recent decision legitimately has none for a moment.
        if repository.load_decision_for_embedding(db, decision_id) is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="decision not found")
        return SimilarCasesResponse(decision_id=decision_id, k=k, items=[])

    rows = repository.find_similar(db, decision_id, k)
    items = [
        SimilarCase(
            decision_id=row["decision_id"],
            application_id=row["application_id"],
            similarity=max(-1.0, min(1.0, float(row["similarity"]))),
            score=int(row["score"]),
            band=row["band"],
            top_reasons=_top_reason_texts(row.get("reason_codes")),
            created_at=row["created_at"],
        )
        for row in rows
    ]
    return SimilarCasesResponse(decision_id=decision_id, k=k, items=items)
