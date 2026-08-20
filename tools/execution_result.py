"""The result shape of one controlled-tool invocation.

Lives in `tools/` (not `backend.app.services`) specifically so agent code
can depend on this type without importing anything SQLAlchemy-adjacent —
see `agents.base`.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class ToolExecutionResult(BaseModel):
    tool_name: str
    status: Literal["success", "error"]
    output: dict | None
    error: str | None
    duration_ms: int
