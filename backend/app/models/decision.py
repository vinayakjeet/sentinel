import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Decision(Base):
    """One scoring decision. Everything needed to reproduce and explain it is persisted (invariant 2)."""

    __tablename__ = "decisions"
    __table_args__ = (Index("ix_decisions_band_created_at", "band", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    application_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("applications.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    band: Mapped[str] = mapped_column(String(16), nullable=False)
    decision: Mapped[str] = mapped_column(String(32), nullable=False)
    p_model: Mapped[float] = mapped_column(Float, nullable=False)
    graph_uplift: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    reason_codes: Mapped[list] = mapped_column(JSONB, nullable=False)
    graph_signals: Mapped[dict] = mapped_column(JSONB, nullable=False)
    thresholds: Mapped[dict] = mapped_column(JSONB, nullable=False)
    model_version: Mapped[str] = mapped_column(String(32), nullable=False)
    latency_ms: Mapped[float] = mapped_column(Float, nullable=False)
    request_id: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC), server_default=func.now(),
        index=True,
    )
