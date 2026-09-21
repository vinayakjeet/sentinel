from dataclasses import dataclass

from fastapi import Request

from app.core.config import Settings
from app.schemas.decision import Thresholds
from app.services.decision_service import DecisionService
from app.services.policy import PolicyEngine
from app.services.scoring import ScoringService, StubScoringService


@dataclass
class Services:
    """Process-wide singletons, built once in the app lifespan."""

    scorer: ScoringService
    policy: PolicyEngine
    decisions: DecisionService


def build_services(settings: Settings) -> Services:
    scorer: ScoringService = StubScoringService()
    policy = PolicyEngine(
        Thresholds(
            step_up=settings.threshold_step_up,
            review=settings.threshold_review,
            decline=settings.threshold_decline,
        )
    )
    return Services(scorer=scorer, policy=policy, decisions=DecisionService(scorer, policy))


def get_services(request: Request) -> Services:
    return request.app.state.services
