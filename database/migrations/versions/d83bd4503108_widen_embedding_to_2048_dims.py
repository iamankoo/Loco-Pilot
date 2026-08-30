"""widen repository_chunks.embedding to 2048 dims

Revision ID: d83bd4503108
Revises: 1767a56b96bc
Create Date: 2026-08-29 00:00:00.000000

nvidia/nemotron-3-embed-1b (the new default real embedding model — see
EMBEDDING_PROVIDER/EMBEDDING_MODEL) is natively 2048-dimensional and
rejects a request to truncate to anything smaller ("dimensions must be one
of 2048", confirmed directly against the API) — unlike OpenAI's
text-embedding-3-* models, which this schema's original 384-dim column was
sized for. Existing rows are cleared rather than migrated in place: a
different embedding dimension is a different vector space entirely, so a
384-dim row can't be reinterpreted as (or padded into) a 2048-dim one.
Losing already-indexed chunks is safe here — `rag.ingestion.indexer`
re-embeds incrementally as files change, and a full re-index is just a
fresh set of executions retrieving against an empty-then-filling index,
never a correctness problem.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import pgvector.sqlalchemy

revision: str = "d83bd4503108"
down_revision: Union[str, None] = "1767a56b96bc"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("TRUNCATE TABLE repository_chunks")
    op.alter_column(
        "repository_chunks",
        "embedding",
        type_=pgvector.sqlalchemy.vector.VECTOR(dim=2048),
        postgresql_using="NULL",
    )


def downgrade() -> None:
    op.execute("TRUNCATE TABLE repository_chunks")
    op.alter_column(
        "repository_chunks",
        "embedding",
        type_=pgvector.sqlalchemy.vector.VECTOR(dim=384),
        postgresql_using="NULL",
    )
