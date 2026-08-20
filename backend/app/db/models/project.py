"""A Project represents a repository/workspace LocoPilot works against."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.db.base import Base
from backend.app.db.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from backend.app.db.models.execution import Execution


class Project(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "projects"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    repo_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    workspace_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)

    executions: Mapped[list["Execution"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
