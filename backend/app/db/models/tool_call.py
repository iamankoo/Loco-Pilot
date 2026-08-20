"""A ToolCall is an audit record of a single controlled-tool invocation.

Input/output are stored as JSONB but truncated before persistence (see
`backend.app.db.repositories.tool_calls`) — this table is an audit trail,
not a blob store. Large payloads belong in an Artifact pointing at
external/object storage in a later phase.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.db.base import Base
from backend.app.db.models.mixins import UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from backend.app.db.models.agent_step import AgentStep
    from backend.app.db.models.execution import Execution


class ToolCallStatus(str, enum.Enum):
    SUCCESS = "success"
    ERROR = "error"


class ToolCall(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "tool_calls"

    execution_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("executions.id", ondelete="CASCADE"), nullable=False
    )
    agent_step_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("agent_steps.id", ondelete="SET NULL"), nullable=True
    )
    tool_name: Mapped[str] = mapped_column(String(128), nullable=False)
    input: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    output: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    execution: Mapped["Execution"] = relationship(back_populates="tool_calls")
    agent_step: Mapped["AgentStep | None"] = relationship(back_populates="tool_calls")
