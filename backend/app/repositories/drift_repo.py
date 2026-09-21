from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import DriftEvent


def add_event(
    db: Session, *, detector: str, stream: str, old_thresholds: dict, new_thresholds: dict, details: dict
) -> DriftEvent:
    ev = DriftEvent(
        detector=detector,
        stream=stream,
        old_thresholds=old_thresholds,
        new_thresholds=new_thresholds,
        details=details,
    )
    db.add(ev)
    db.flush()
    return ev


def recent_events(db: Session, limit: int = 50) -> list[DriftEvent]:
    return list(db.scalars(select(DriftEvent).order_by(DriftEvent.ts.desc(), DriftEvent.id.desc()).limit(limit)))
