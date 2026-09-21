import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Application, Decision


def add_application(db: Session, app_row: Application) -> Application:
    db.add(app_row)
    db.flush()
    return app_row


def add_decision(db: Session, decision: Decision) -> Decision:
    db.add(decision)
    db.flush()
    return decision


def get_decision(db: Session, decision_id: uuid.UUID) -> tuple[Decision, Application] | None:
    row = db.execute(
        select(Decision, Application)
        .join(Application, Application.id == Decision.application_id)
        .where(Decision.id == decision_id)
    ).first()
    return (row[0], row[1]) if row else None


def list_decisions(
    db: Session, band: str | None, limit: int, offset: int
) -> tuple[list[tuple[Decision, Application]], int]:
    base = select(Decision, Application).join(Application, Application.id == Decision.application_id)
    count = select(func.count()).select_from(Decision)
    if band:
        base = base.where(Decision.band == band)
        count = count.where(Decision.band == band)
    rows = db.execute(base.order_by(Decision.created_at.desc()).limit(limit).offset(offset)).all()
    total = db.execute(count).scalar_one()
    return [(r[0], r[1]) for r in rows], total
