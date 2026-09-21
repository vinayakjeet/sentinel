import logging
import threading

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.session import SessionLocal
from app.models import DriftEvent
from app.repositories import audit_repo, drift_repo
from app.schemas.decision import Thresholds
from app.schemas.metrics import DriftEventOut, DriftStatus
from app.services.broadcaster import Broadcaster
from app.services.drift import Detection, DriftMonitor
from app.services.policy import PolicyEngine

logger = logging.getLogger(__name__)


class DriftService:
    """Acts on ADWIN detections: tighten bands, persist a drift_events row + audit entry, push an SSE `drift` event."""

    def __init__(self, settings: Settings, policy: PolicyEngine, broadcaster: Broadcaster) -> None:
        self.s = settings
        self.policy = policy
        self.broadcaster = broadcaster
        self.monitor = DriftMonitor(
            delta=settings.adwin_delta,
            label_lag=settings.label_lag_events,
            cooldown_events=settings.drift_cooldown_events,
        )
        self._tightenings = 0
        self._lock = threading.Lock()

    def observe(self, p: float, label: int | None, source: str) -> None:
        for detection in self.monitor.observe(p, label):
            self._act(detection, source)

    def _act(self, d: Detection, source: str) -> None:
        with self._lock:
            if self._tightenings < self.s.drift_max_tightenings:
                old, new = self.policy.tighten(self.s.drift_tighten_delta)
                self._tightenings += 1
            else:  # cap reached: record the detection, leave thresholds where they are
                old = new = self.policy.thresholds
        details = {
            "source": source,
            "events_seen": d.events_seen,
            "window_width": d.window_width,
            "window_mean": round(d.window_mean, 4),
            "adwin_delta": self.s.adwin_delta,
            "tightened": old != new,
        }
        with SessionLocal() as db:
            ev = drift_repo.add_event(
                db,
                detector="adwin",
                stream=d.stream,
                old_thresholds=old.model_dump(),
                new_thresholds=new.model_dump(),
                details=details,
            )
            audit_repo.write(
                db, actor="system", action="drift.detected", resource_type="drift_event",
                resource_id=str(ev.id), details={"stream": d.stream, **details},
            )
            db.commit()
            out = _to_out(ev)
        logger.warning(
            "drift detected",
            extra={"stream": d.stream, "old": old.model_dump(), "new": new.model_dump(), **details},
        )
        self.broadcaster.publish("drift", out.model_dump_json())

    def status(self, db: Session) -> DriftStatus:
        current, base = self.policy.thresholds, self.policy.base
        return DriftStatus(
            state="stable" if current == base else "drift_detected",
            thresholds=current,
            base_thresholds=base,
            events=[_to_out(e) for e in drift_repo.recent_events(db)],
        )

    def reset(self, db: Session, actor: str) -> DriftStatus:
        with self._lock:
            old, base = self.policy.reset()
            self._tightenings = 0
        self.monitor.reset()
        audit_repo.write(
            db, actor=actor, action="drift.reset", resource_type="thresholds",
            details={"old": old.model_dump(), "new": base.model_dump()},
        )
        db.commit()
        return self.status(db)


def _to_out(e: DriftEvent) -> DriftEventOut:
    return DriftEventOut(
        id=e.id,
        ts=e.ts,
        detector=e.detector,
        stream=e.stream,
        old_thresholds=Thresholds(**e.old_thresholds),
        new_thresholds=Thresholds(**e.new_thresholds),
        details=e.details,
    )
