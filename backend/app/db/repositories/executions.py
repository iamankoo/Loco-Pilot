from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select
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


def _apply_execution_filters(stmt, *, project_id: uuid.UUID | None, status: str | None):
    if project_id is not None:
        stmt = stmt.where(Execution.project_id == project_id)
    if status is not None:
        stmt = stmt.where(Execution.status == status)
    return stmt


async def list_executions(
    db: AsyncSession,
    *,
    project_id: uuid.UUID | None = None,
    status: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> list[Execution]:
    stmt = _apply_execution_filters(select(Execution), project_id=project_id, status=status)
    stmt = stmt.order_by(Execution.created_at.desc()).limit(limit).offset(offset)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def count_executions(
    db: AsyncSession, *, project_id: uuid.UUID | None = None, status: str | None = None
) -> int:
    stmt = _apply_execution_filters(select(func.count()).select_from(Execution), project_id=project_id, status=status)
    result = await db.execute(stmt)
    return result.scalar_one()


async def get_latest_execution_for_project(db: AsyncSession, project_id: uuid.UUID) -> Execution | None:
    stmt = (
        select(Execution)
        .where(Execution.project_id == project_id)
        .order_by(Execution.created_at.desc())
        .limit(1)
    )
    result = await db.execute(stmt)
    return result.scalars().first()


async def get_execution_status_counts_for_project(db: AsyncSession, project_id: uuid.UUID) -> dict[str, int]:
    stmt = (
        select(Execution.status, func.count())
        .where(Execution.project_id == project_id)
        .group_by(Execution.status)
    )
    result = await db.execute(stmt)
    return {status: count for status, count in result.all()}
