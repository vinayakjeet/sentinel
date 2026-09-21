import uuid
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class Band(StrEnum):
    APPROVE = "APPROVE"
    STEP_UP = "STEP_UP"
    REVIEW = "REVIEW"
    DECLINE = "DECLINE"


class DecisionOutcome(StrEnum):
    """What happens to the application. Band = risk tier; decision = resulting application status."""

    APPROVED = "approved"
    PENDING_VERIFICATION = "pending_verification"
    PENDING_REVIEW = "pending_review"
    DECLINED = "declined"


BAND_TO_DECISION = {
    Band.APPROVE: DecisionOutcome.APPROVED,
    Band.STEP_UP: DecisionOutcome.PENDING_VERIFICATION,
    Band.REVIEW: DecisionOutcome.PENDING_REVIEW,
    Band.DECLINE: DecisionOutcome.DECLINED,
}


class ReasonCode(BaseModel):
    feature: str
    reason: str
    ecoa_category: str
    contribution: float = Field(description="SHAP contribution toward fraud (log-odds, > 0)")


class GraphSignals(BaseModel):
    component_size: int = 0
    distinct_names_per_device: int = 0
    known_fraud_2hop: int = 0
    component_velocity_24h: int = 0


class Thresholds(BaseModel):
    """Score cut-offs: APPROVE < step_up <= STEP_UP < review <= REVIEW < decline <= DECLINE."""

    step_up: int
    review: int
    decline: int


class DecisionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    decision_id: uuid.UUID
    application_id: uuid.UUID
    external_ref: str | None = None
    score: int = Field(ge=0, le=1000)
    band: Band
    decision: DecisionOutcome
    reason_codes: list[ReasonCode]
    graph_signals: GraphSignals
    graph_uplift: float = Field(ge=0.0, le=1.0)
    model_version: str
    latency_ms: float
    created_at: datetime


class DecisionList(BaseModel):
    items: list[DecisionResponse]
    total: int
    limit: int
    offset: int
