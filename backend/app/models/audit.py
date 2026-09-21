from datetime import datetime

from sqlalchemy import BigInteger, DateTime, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class DriftEvent(Base):
    __tablename__ = "drift_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), index=True)
    detector: Mapped[str] = mapped_column(String(32), nullable=False)
    stream: Mapped[str] = mapped_column(String(32), nullable=False)
    old_thresholds: Mapped[dict] = mapped_column(JSONB, nullable=False)
    new_thresholds: Mapped[dict] = mapped_column(JSONB, nullable=False)
    details: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)


class AuditLog(Base):
    """Append-only record of every state-changing action (decisions, stream control, drift, logins)."""

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), index=True)
    request_id: Mapped[str | None] = mapped_column(String(64))
    actor: Mapped[str] = mapped_column(String(64), nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    resource_type: Mapped[str | None] = mapped_column(String(32))
    resource_id: Mapped[str | None] = mapped_column(String(64))
    details: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
