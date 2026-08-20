"""POST /api/v1/executions and GET /api/v1/executions/{id}.

No arbitrary tool execution or raw-command endpoint here or anywhere in
the API — this is the only way to trigger agent activity over HTTP, and it
only ever accepts a task description plus a project/workspace reference.
The route never touches agents or the graph directly; it calls the
execution service (see `backend.app.services.execution_service`).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.models.execution import ExecutionStatus
from backend.app.db.repositories.executions import get_execution
from backend.app.db.repositories.projects import create_project, get_project
from backend.app.db.session import get_db
from backend.app.services.execution_service import (
    ExecutionServiceError,
    cancel_execution,
    create_and_run_execution,
    run_execution,
)
from tools.workspace import Workspace, WorkspaceError

router = APIRouter(prefix="/executions", tags=["executions"])


class CreateExecutionRequest(BaseModel):
    task: str = Field(min_length=1)
    project_id: uuid.UUID | None = None
    workspace_path: str | None = None
    project_name: str | None = None


class ExecutionResponse(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    task: str
    status: str
    current_agent: str | None
    error_message: str | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None

    model_config = {"from_attributes": True}


@router.post("", status_code=201, response_model=ExecutionResponse)
async def create_execution_endpoint(
    payload: CreateExecutionRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
) -> ExecutionResponse:
    project_id = payload.project_id

    if project_id is None:
        if not payload.workspace_path:
            raise HTTPException(422, "Either project_id or workspace_path must be provided.")
        try:
            Workspace.at(payload.workspace_path)
        except WorkspaceError as exc:
            raise HTTPException(422, f"Invalid workspace_path: {exc}") from exc
        project = await create_project(
            db, name=payload.project_name or payload.workspace_path, workspace_path=payload.workspace_path
        )
        project_id = project.id
    else:
        project = await get_project(db, project_id)
        if project is None:
            raise HTTPException(404, "Project not found.")

    try:
        execution = await create_and_run_execution(db, project_id=project_id, task=payload.task)
    except ExecutionServiceError as exc:
        raise HTTPException(422, str(exc)) from exc

    background_tasks.add_task(run_execution, execution.id)
    return ExecutionResponse.model_validate(execution)


@router.get("/{execution_id}", response_model=ExecutionResponse)
async def get_execution_endpoint(execution_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> ExecutionResponse:
    execution = await get_execution(db, execution_id)
    if execution is None:
        raise HTTPException(404, "Execution not found.")
    return ExecutionResponse.model_validate(execution)


@router.post("/{execution_id}/cancel", status_code=202, response_model=ExecutionResponse)
async def cancel_execution_endpoint(
    execution_id: uuid.UUID, db: AsyncSession = Depends(get_db)
) -> ExecutionResponse:
    """Signals cancellation — checked between agent turns (see
    `agents.graph.make_agent_node`), so a command already running inside
    the Docker sandbox completes before the next checkpoint rather than
    being force-killed mid-execution. Has no effect on an execution that
    has already reached a terminal status."""
    execution = await get_execution(db, execution_id)
    if execution is None:
        raise HTTPException(404, "Execution not found.")
    if execution.status in (
        ExecutionStatus.PENDING.value,
        ExecutionStatus.RUNNING.value,
    ):
        cancel_execution(execution_id)
    return ExecutionResponse.model_validate(execution)
