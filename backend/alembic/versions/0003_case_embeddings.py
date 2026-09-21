"""case_embeddings with an HNSW cosine index (DESIGN §8).

Lane B migration. Chained onto Lane A's 0002_core_tables per their coordination note; their
migration files are not edited. If Lane A adds a later migration it chains after this one.

Revision ID: 0003_case_embeddings
Revises: 0002_core_tables
"""

from alembic import op

revision = "0003_case_embeddings"
down_revision = "0002_core_tables"
branch_labels = None
depends_on = None

EMBEDDING_DIM = 384  # all-MiniLM-L6-v2


def upgrade() -> None:
    # The vector extension is created by 0001_vector; this migration only depends on it existing.
    op.execute(
        f"""
        CREATE TABLE case_embeddings (
            decision_id UUID PRIMARY KEY REFERENCES decisions(id) ON DELETE CASCADE,
            embedding   vector({EMBEDDING_DIM}) NOT NULL,
            metadata    JSONB NOT NULL DEFAULT '{{}}'::jsonb,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )

    # HNSW with cosine distance, matching the `<=>` operator the similarity query orders by.
    # m / ef_construction are left at pgvector defaults (16 / 64): the demo corpus is ~150k rows,
    # where the defaults already give sub-millisecond probes, and raising them only slows the
    # backfill down.
    op.execute(
        """
        CREATE INDEX ix_case_embeddings_hnsw
            ON case_embeddings
            USING hnsw (embedding vector_cosine_ops)
        """
    )
    op.execute("CREATE INDEX ix_case_embeddings_created_at ON case_embeddings (created_at)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_case_embeddings_created_at")
    op.execute("DROP INDEX IF EXISTS ix_case_embeddings_hnsw")
    op.execute("DROP TABLE IF EXISTS case_embeddings")
