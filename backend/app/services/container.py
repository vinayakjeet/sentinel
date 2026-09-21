import logging
from dataclasses import dataclass

from fastapi import Request

from app.core.config import Settings
from app.schemas.decision import DecisionResponse, Thresholds
from app.services.broadcaster import Broadcaster
from app.services.decision_service import DecisionService
from app.services.drift_service import DriftService
from app.services.entity_resolver import EntityResolver
from app.services.graph_service import GraphService
from app.services.metrics import MetricsCollector
from app.services.policy import PolicyEngine
from app.services.replay import ReplayService
from app.services.scoring import ScoringService, StubScoringService

logger = logging.getLogger(__name__)


@dataclass
class Services:
    """Process-wide singletons, built once in the app lifespan (single uvicorn worker by design)."""

    scorer: ScoringService
    policy: PolicyEngine
    graph: GraphService
    decisions: DecisionService
    metrics: MetricsCollector
    broadcaster: Broadcaster
    drift: DriftService
    replay: ReplayService


class PostDecision:
    """Runs after every committed decision. Never raises: the decision is already persisted."""

    def __init__(self, metrics: MetricsCollector, broadcaster: Broadcaster, drift: DriftService) -> None:
        self.metrics = metrics
        self.broadcaster = broadcaster
        self.drift = drift

    def __call__(self, response: DecisionResponse, *, history: bool, label: int | None, source: str) -> None:
        try:
            self.metrics.record(response.latency_ms, response.band.value)
            if history:  # backfill: no live feed, no drift signal
                return
            self.broadcaster.publish("decision", response.model_dump_json())
            self.drift.observe(response.score / 1000, label, source)
        except Exception:
            logger.exception("post-decision hook failed", extra={"decision_id": str(response.decision_id)})


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
    metrics = MetricsCollector()
    broadcaster = Broadcaster()
    drift = DriftService(settings, policy, broadcaster)
    decisions = DecisionService(scorer, policy, EntityResolver(), graph)
    decisions.observer = PostDecision(metrics, broadcaster, drift)
    return Services(
        scorer=scorer,
        policy=policy,
        graph=graph,
        decisions=decisions,
        metrics=metrics,
        broadcaster=broadcaster,
        drift=drift,
        replay=ReplayService(settings, decisions, broadcaster),
    )


def get_services(request: Request) -> Services:
    return request.app.state.services
