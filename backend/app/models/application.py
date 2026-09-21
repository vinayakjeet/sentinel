import uuid
from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, SmallInteger, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Application(Base):
    """A credit application. Raw BAF features only; identifiers are never stored in clear (see entities)."""

    __tablename__ = "applications"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    external_ref: Mapped[str | None] = mapped_column(String(64), index=True)
    features: Mapped[dict] = mapped_column(JSONB, nullable=False)
    name_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    source_stream: Mapped[str] = mapped_column(String(16), nullable=False, default="api")
    is_history: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Confirmed label; only set for history loads (simulated delayed ground truth).
    fraud_bool: Mapped[int | None] = mapped_column(SmallInteger)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC), server_default=func.now(),
        index=True,
    )
