from dataclasses import dataclass, field
from typing import Protocol

from app.schemas.application import ApplicationEvent
from app.schemas.decision import ReasonCode


@dataclass(frozen=True)
class ModelScore:
    p_model: float  # blended model probability in [0, 1], before graph uplift
    reason_codes: list[ReasonCode] = field(default_factory=list)


class ScoringService(Protocol):
    model_version: str

    def score(self, event: ApplicationEvent) -> ModelScore: ...


class StubScoringService:
    """Placeholder until Lane B's artifacts land: constant probability, no reasons."""

    model_version = "stub-0"

    def score(self, event: ApplicationEvent) -> ModelScore:
        return ModelScore(p_model=0.5)
