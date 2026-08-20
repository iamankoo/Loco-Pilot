from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.models.execution import Execution, ExecutionStatus


async def create_execution(db: AsyncSession, *, project_id: uuid.UUID, task: str) -> Execution:
    execution = Execution(project_id=project_id, task=task, status=ExecutionStatus.PENDING.value)
    db.add(execution)
    await db.commit()
    await db.refresh(execution)
    return execution


async def get_execution(db: AsyncSession, execution_id: uuid.UUID) -> Execution | None:
    return await db.get(Execution, execution_id)


async def update_execution_status(
    db: AsyncSession,
    execution_id: uuid.UUID,
    *,
    status: ExecutionStatus,
    current_agent: str | None = None,
    error_message: str | None = None,
    mark_started: bool = False,
    mark_completed: bool = False,
) -> Execution:
    execution = await db.get(Execution, execution_id)
    if execution is None:
        raise ValueError(f"Execution not found: {execution_id}")

    execution.status = status.value
    if current_agent is not None:
        execution.current_agent = current_agent
    if error_message is not None:
        execution.error_message = error_message
    if mark_started and execution.started_at is None:
        execution.started_at = datetime.now(timezone.utc)
    if mark_completed:
        execution.completed_at = datetime.now(timezone.utc)

    await db.commit()
    await db.refresh(execution)
    return execution
