import logging
import time
from typing import Protocol

from sqlalchemy.orm import Session

from app.core.logging import request_id_ctx
from app.models import Application, Decision
from app.repositories import audit_repo, decision_repo
from app.schemas.application import ApplicationEvent
from app.schemas.decision import DecisionResponse
from app.services.entity_resolver import EntityResolver
from app.services.graph_service import GraphService
from app.services.normalize import normalize_name, sha256_hex
from app.services.policy import PolicyEngine
from app.services.scoring import ScoringService

logger = logging.getLogger(__name__)


class DecisionObserver(Protocol):
    def __call__(self, response: DecisionResponse, *, history: bool, label: int | None, source: str) -> None: ...


class DecisionService:
    """validate (route) -> persist application -> entities + graph signals -> score -> uplift -> policy
    -> persist decision + audit -> response. One transaction."""

    def __init__(
        self, scorer: ScoringService, policy: PolicyEngine, resolver: EntityResolver, graph: GraphService
    ) -> None:
        self.scorer = scorer
        self.policy = policy
        self.resolver = resolver
        self.graph = graph
        self.observer: DecisionObserver | None = None  # set by the container (metrics, SSE, drift)

    def decide(
        self,
        db: Session,
        event: ApplicationEvent,
        *,
        actor: str,
        source_stream: str = "api",
        started_at: float | None = None,
        drift_label: int | None = None,
    ) -> DecisionResponse:
        t0 = started_at if started_at is not None else time.perf_counter()

        app_row = decision_repo.add_application(
            db,
            Application(
                external_ref=event.external_ref,
                features=event.features(),
                name_hash=sha256_hex(normalize_name(event.applicant_name)),
                source_stream=source_stream,
                is_history=event.history,
                fraud_bool=event.label(),
            ),
        )

        self.resolver.resolve(db, app_row.id, event)
        signals = self.graph.signals(db, app_row.id)
        uplift = self.graph.uplift(signals)

        model_score = self.scorer.score(event)
        p_final = min(1.0, model_score.p_model + uplift)
        score = round(1000 * p_final)
        band, thresholds = self.policy.classify(score)
        outcome = self.policy.decision_for(band)

        decision = decision_repo.add_decision(
            db,
            Decision(
                application_id=app_row.id,
                score=score,
                band=band.value,
                decision=outcome.value,
                p_model=model_score.p_model,
                graph_uplift=uplift,
                reason_codes=[r.model_dump() for r in model_score.reason_codes],
                graph_signals=signals.model_dump(),
                thresholds=thresholds.model_dump(),
                model_version=self.scorer.model_version,
                latency_ms=0.0,
                request_id=request_id_ctx.get(),
            ),
        )
        audit_repo.write(
            db,
            actor=actor,
            action="decision.created",
            resource_type="decision",
            resource_id=str(decision.id),
            details={"band": band.value, "score": score, "source_stream": source_stream},
        )
        decision.latency_ms = round((time.perf_counter() - t0) * 1000, 2)
        db.commit()

        logger.info(
            "decision",
            extra={
                "decision_id": str(decision.id),
                "band": band.value,
                "score": score,
                "latency_ms": decision.latency_ms,
                "source_stream": source_stream,
            },
        )
        response = to_response(decision, app_row)
        if self.observer is not None:
            # `drift_label` is the delayed ground truth the replay knows; it feeds the drift error stream only
            # and is never persisted (only history loads persist labels).
            self.observer(response, history=event.history, label=drift_label, source=source_stream)
        return response


def to_response(decision: Decision, app_row: Application) -> DecisionResponse:
    return DecisionResponse(
        decision_id=decision.id,
        application_id=app_row.id,
        external_ref=app_row.external_ref,
        score=decision.score,
        band=decision.band,
        decision=decision.decision,
        reason_codes=decision.reason_codes,
        graph_signals=decision.graph_signals,
        graph_uplift=decision.graph_uplift,
        model_version=decision.model_version,
        latency_ms=decision.latency_ms,
        created_at=decision.created_at,
    )

