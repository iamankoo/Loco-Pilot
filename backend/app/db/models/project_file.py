"""A durable copy of one file from a project's workspace.

Hosted deployments (e.g. Render's free tier) have an ephemeral disk that is
wiped on every redeploy or idle spin-down. After each execution the
workspace's files are copied here so the result can still be saved to the
user's computer — and the workspace rebuilt — after a restart.
"""

from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, Integer, LargeBinary, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.db.base import Base
from backend.app.db.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class ProjectFile(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "project_files"
    __table_args__ = (UniqueConstraint("project_id", "path", name="uq_project_files_project_path"),)

    project_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Workspace-relative, POSIX-style.
    path: Mapped[str] = mapped_column(String(1024), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
