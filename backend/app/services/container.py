import logging
from dataclasses import dataclass

from fastapi import Request

from app.core.config import Settings
from app.schemas.decision import Thresholds
from app.services.decision_service import DecisionService
from app.services.entity_resolver import EntityResolver
from app.services.graph_service import GraphService
from app.services.policy import PolicyEngine
from app.services.scoring import ScoringService, StubScoringService

logger = logging.getLogger(__name__)


@dataclass
class Services:
    """Process-wide singletons, built once in the app lifespan."""

    scorer: ScoringService
    policy: PolicyEngine
    graph: GraphService
    decisions: DecisionService


def build_scorer(settings: Settings) -> ScoringService:
    """Real model if Lane B's artifacts + ml.featurize are present; otherwise the stub (loudly)."""
    try:
        from app.services.model_registry import ModelScoringService, import_featurizer, load_artifacts

        artifacts = load_artifacts(settings.artifacts_dir, settings.model_version)
        scorer = ModelScoringService(artifacts, import_featurizer())
        logger.info("model loaded", extra={"model_version": scorer.model_version, "dir": settings.artifacts_dir})
        return scorer
    except (FileNotFoundError, ModuleNotFoundError, ImportError, KeyError) as exc:
        logger.warning(
            "model artifacts unavailable; using STUB scorer",
            extra={"error": repr(exc), "dir": settings.artifacts_dir},
        )
        return StubScoringService()


def build_services(settings: Settings) -> Services:
    scorer = build_scorer(settings)
    policy = PolicyEngine(
        Thresholds(
            step_up=settings.threshold_step_up,
            review=settings.threshold_review,
            decline=settings.threshold_decline,
        )
    )
    graph = GraphService(settings)
    return Services(
        scorer=scorer,
        policy=policy,
        graph=graph,
        decisions=DecisionService(scorer, policy, EntityResolver(), graph),
    )


def get_services(request: Request) -> Services:
    return request.app.state.services
