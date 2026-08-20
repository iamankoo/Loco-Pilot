"""Bridges the tool system to persistence: Execution -> AgentStep -> ToolCall.

This is the seam a future orchestrator calls through; it does not itself
decide *when* to call a tool (no orchestrator exists yet), only *how* a
call is validated, logged, and recorded once requested.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.logging import get_logger
from backend.app.db.repositories.tool_calls import create_tool_call
from backend.app.security.secret_scrubber import scrub_secrets
from tools.base import Permission, ToolContext, ToolError, ToolPermissionError
from tools.execution_result import ToolExecutionResult
from tools.registry import ToolRegistry

logger = get_logger(component="tool_execution")


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
        # Secret scrubbing happens here, before anything reaches the
        # database — the ToolExecutionResult returned to the caller below
        # is NOT scrubbed, so the agent still reasons over full-fidelity
        # output (e.g. to remove a hardcoded secret it just found).
        await create_tool_call(
            db,
            execution_id=uuid.UUID(context.execution_id),
            agent_step_id=uuid.UUID(context.agent_step_id) if context.agent_step_id else None,
            tool_name=tool_name,
            input=scrub_secrets(tool_input),
            output=scrub_secrets(output_payload) if output_payload is not None else None,
            status=status,
            duration_ms=duration_ms,
            error_message=scrub_secrets(error_message) if error_message is not None else None,
        )

    return ToolExecutionResult(
        tool_name=tool_name,
        status=status,
        output=output_payload,
        error=error_message,
        duration_ms=duration_ms,
    )


@dataclass
class BoundToolRunner:
    """The only tool-calling surface an agent ever sees.

    Bound to one agent's permission set, one execution/agent-step context,
    and (if available) a DB session for persistence — none of which the
    agent itself has direct access to. This is what keeps agent classes
    free of any SQLAlchemy dependency: they call `.call(name, input)` and
    get back a `ToolExecutionResult`; everything else is closed over here
    by the caller (the graph node) that constructs this runner.
    """

    registry: ToolRegistry
    context: ToolContext
    permissions: set[Permission]
    db: AsyncSession | None = None

    async def call(self, tool_name: str, tool_input: dict) -> ToolExecutionResult:
        if tool_name not in self.available_tools():
            raise ToolPermissionError(f"Tool '{tool_name}' is not permitted for this agent.")
        return await execute_tool(self.registry, tool_name, tool_input, self.context, db=self.db)

    def available_tools(self) -> set[str]:
        return {t.name for t in self.registry.list_tools(permissions=self.permissions)}
