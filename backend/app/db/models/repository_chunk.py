"""A RepositoryChunk is one embedded, indexed slice of a project's source file.

`embedding` is fixed-width (`EMBEDDING_DIMENSION`) regardless of which
embedding provider produced it — see `rag.embeddings` — so the pgvector
column and its distance operators don't need to change if the provider
does.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.db.base import Base
from backend.app.db.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin

EMBEDDING_DIMENSION = 2048


class RepositoryChunk(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "repository_chunks"
    __table_args__ = (Index("ix_repository_chunks_project_file", "project_id", "file_path"),)

    project_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    file_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIMENSION), nullable=False)
    chunk_metadata: Mapped[dict | None] = mapped_column("metadata", JSONB, nullable=True)
