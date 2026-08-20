from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.models.tool_call import ToolCall
from backend.app.db.repositories.truncate import truncate_for_storage


async def create_tool_call(
    db: AsyncSession,
    *,
    execution_id: uuid.UUID,
    tool_name: str,
    status: str,
    duration_ms: int | None,
    agent_step_id: uuid.UUID | None = None,
    input: dict | None = None,
    output: dict | None = None,
    error_message: str | None = None,
) -> ToolCall:
    tool_call = ToolCall(
        execution_id=execution_id,
        agent_step_id=agent_step_id,
        tool_name=tool_name,
        input=truncate_for_storage(input) if input is not None else None,
        output=truncate_for_storage(output) if output is not None else None,
        status=status,
        duration_ms=duration_ms,
        error_message=error_message,
    )
    db.add(tool_call)
    await db.commit()
    await db.refresh(tool_call)
    return tool_call
