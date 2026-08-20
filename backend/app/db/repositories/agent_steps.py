from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.models.agent_step import AgentStep, AgentStepStatus


async def create_agent_step(
    db: AsyncSession,
    *,
    execution_id: uuid.UUID,
    agent_name: str,
    input_metadata: dict | None = None,
) -> AgentStep:
    step = AgentStep(
        execution_id=execution_id,
        agent_name=agent_name,
        status=AgentStepStatus.RUNNING.value,
        input_metadata=input_metadata,
        started_at=datetime.now(timezone.utc),
    )
    db.add(step)
    await db.commit()
    await db.refresh(step)
    return step


async def complete_agent_step(
    db: AsyncSession,
    step_id: uuid.UUID,
    *,
    status: AgentStepStatus,
    output_metadata: dict | None = None,
    error_message: str | None = None,
) -> AgentStep:
    step = await db.get(AgentStep, step_id)
    if step is None:
        raise ValueError(f"AgentStep not found: {step_id}")

    step.status = status.value
    step.output_metadata = output_metadata
    step.error_message = error_message
    step.completed_at = datetime.now(timezone.utc)

    await db.commit()
    await db.refresh(step)
    return step


async def list_agent_steps_for_execution(db: AsyncSession, execution_id: uuid.UUID) -> list[AgentStep]:
    stmt = (
        select(AgentStep)
        .where(AgentStep.execution_id == execution_id)
        .order_by(AgentStep.created_at.asc())
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())
