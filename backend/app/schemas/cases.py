"""Contract for GET /cases/{decision_id}/similar (implemented by Lane B in app/semantic/, which imports these)."""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.decision import Band


class SimilarCase(BaseModel):
    decision_id: uuid.UUID
    application_id: uuid.UUID
    similarity: float = Field(ge=-1.0, le=1.0, description="Cosine similarity of case narratives")
    score: int
    band: Band
    top_reasons: list[str] = Field(description="Reason texts of the similar case, highest contribution first")
    created_at: datetime


class SimilarCasesResponse(BaseModel):
    decision_id: uuid.UUID
    k: int
    items: list[SimilarCase]
