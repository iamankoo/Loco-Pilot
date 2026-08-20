"""An Artifact references a durable output of an Execution (diff, log, file).

`path` is a location reference (workspace-relative path today; an
object-storage URI/key in a later phase) rather than inline content, so
this table stays small regardless of artifact size.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.db.base import Base
from backend.app.db.models.mixins import UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from backend.app.db.models.execution import Execution


class Artifact(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "artifacts"

    execution_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("executions.id", ondelete="CASCADE"), nullable=False
    )
    artifact_type: Mapped[str] = mapped_column(String(64), nullable=False)
    path: Mapped[str] = mapped_column(String(1024), nullable=False)
    artifact_metadata: Mapped[dict | None] = mapped_column("metadata", JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    execution: Mapped["Execution"] = relationship(back_populates="artifacts")
