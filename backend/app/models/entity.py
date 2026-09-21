import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

ENTITY_TYPES = ("device", "email", "phone", "ip", "address")


class Entity(Base):
    """A shared identifier (device, email, ...), stored only as sha256 of its normalised value."""

    __tablename__ = "entities"
    __table_args__ = (
        UniqueConstraint("type", "value_hash", name="uq_entities_type_value_hash"),
        CheckConstraint(f"type IN {ENTITY_TYPES}", name="ck_entities_type"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    type: Mapped[str] = mapped_column(String(16), nullable=False)
    value_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    fraud_flag: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")


class EntityLink(Base):
    """Bipartite edge application <-> entity."""

    __tablename__ = "entity_links"
    __table_args__ = (UniqueConstraint("application_id", "entity_id", name="uq_entity_links_app_entity"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    application_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("applications.id", ondelete="CASCADE"), nullable=False, index=True
    )
    entity_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("entities.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
