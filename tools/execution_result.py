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
    # The coarse, machine-checkable classification from `ToolError.code`
    # (e.g. "NOT_A_GIT_REPOSITORY", "PATH_OUTSIDE_WORKSPACE"), when the tool
    # raised one — None for a success, an unclassified ToolError, or an
    # unexpected exception. Lets a caller (agents.reviewer) distinguish a
    # specific, known-benign failure kind from a genuinely unexpected one
    # without parsing the human-readable `error` message text.
    error_code: str | None = None
    duration_ms: int
