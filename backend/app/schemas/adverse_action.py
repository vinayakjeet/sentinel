import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.decision import DecisionOutcome


class PrincipalReason(BaseModel):
    rank: int = Field(ge=1, le=4)
    reason: str
    ecoa_category: str


class AdverseActionNotice(BaseModel):
    """Reg B (12 CFR 1002.9)-shaped notice. Applicant-facing: plain-language reasons only, no raw features/scores."""

    decision_id: uuid.UUID
    application_id: uuid.UUID
    action_taken: DecisionOutcome
    notice_date: datetime
    principal_reasons: list[PrincipalReason]
    ecoa_notice: str
    right_to_request_reasons: str
