"""Bridges the tool system to persistence: Execution -> AgentStep -> ToolCall.

This is the seam a future orchestrator calls through; it does not itself
decide *when* to call a tool (no orchestrator exists yet), only *how* a
call is validated, logged, and recorded once requested.
"""

from __future__ import annotations

import time
import uuid
from typing import Literal

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.logging import get_logger
from backend.app.db.repositories.tool_calls import create_tool_call
from tools.base import ToolContext, ToolError
from tools.registry import ToolRegistry

logger = get_logger(component="tool_execution")


class ToolExecutionResult(BaseModel):
    tool_name: str
    status: Literal["success", "error"]
    output: dict | None
    error: str | None
    duration_ms: int


async def execute_tool(
    registry: ToolRegistry,
    tool_name: str,
    tool_input: dict,
    context: ToolContext,
    *,
    db: AsyncSession | None = None,
) -> ToolExecutionResult:
    """Validate, run, log, and (if a session is given) persist one tool call.

    Raises `ToolNotFoundError` for an unknown tool name (a caller bug, not a
    tool-execution failure). Input validation errors and `ToolError`s raised
    by the tool itself are captured into the returned result instead of
    propagating, so a future orchestrator can inspect `.status` and decide
    to retry/debug rather than crash.
    """
    tool = registry.get(tool_name)  # raises ToolNotFoundError for unknown tools

    start = time.monotonic()
    status: Literal["success", "error"] = "success"
    error_message: str | None = None
    output_payload: dict | None = None

    try:
        parsed_input = tool.input_model.model_validate(tool_input)
        output = await tool.run(parsed_input, context)
        output_payload = output.model_dump(mode="json")
    except ToolError as exc:
        status = "error"
        error_message = str(exc)
    except Exception as exc:  # noqa: BLE001 - unexpected tool failures must still be recorded, not crash the caller
        status = "error"
        error_message = f"Unexpected error: {exc}"

    duration_ms = int((time.monotonic() - start) * 1000)

    logger.info(
        "tool_call_completed",
        tool=tool_name,
        status=status,
        duration_ms=duration_ms,
        execution_id=context.execution_id,
        agent_step_id=context.agent_step_id,
    )

    if db is not None and context.execution_id is not None:
        await create_tool_call(
            db,
            execution_id=uuid.UUID(context.execution_id),
            agent_step_id=uuid.UUID(context.agent_step_id) if context.agent_step_id else None,
            tool_name=tool_name,
            input=tool_input,
            output=output_payload,
            status=status,
            duration_ms=duration_ms,
            error_message=error_message,
        )

    return ToolExecutionResult(
        tool_name=tool_name,
        status=status,
        output=output_payload,
        error=error_message,
        duration_ms=duration_ms,
    )
