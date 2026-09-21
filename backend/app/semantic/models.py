"""ORM model for case_embeddings (DESIGN §8)."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import UserDefinedType

from app.db.base import Base

EMBEDDING_DIM = 384  # all-MiniLM-L6-v2


class Vector(UserDefinedType):
    """Minimal pgvector binding.

    Deliberately hand-rolled rather than depending on the `pgvector` package: it keeps Lane A's
    image free of another dependency, and pgvector's text representation is trivial. Values move
    as '[0.1,0.2,...]', which is exactly what the extension accepts and returns.
    """

    cache_ok = True

    def __init__(self, dim: int = EMBEDDING_DIM) -> None:
        self.dim = dim

    def get_col_spec(self, **kw) -> str:
        return f"vector({self.dim})"

    def bind_processor(self, dialect):
        def process(value):
            if value is None:
                return None
            return "[" + ",".join(format(float(v), ".8f") for v in value) + "]"

        return process

    def result_processor(self, dialect, coltype):
        def process(value):
            if value is None:
                return None
            if isinstance(value, list | tuple):
                return [float(v) for v in value]
            return [float(x) for x in str(value).strip("[]").split(",") if x]

        return process


class CaseEmbedding(Base):
    """One embedded case narrative per decision."""

    __tablename__ = "case_embeddings"

    decision_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("decisions.id", ondelete="CASCADE"), primary_key=True
    )
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIM), nullable=False)
    # "metadata" is reserved on SQLAlchemy's declarative Base, so the attribute is `meta` while the
    # column keeps the name DESIGN §8 specifies.
    meta: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC), server_default=func.now()
    )
