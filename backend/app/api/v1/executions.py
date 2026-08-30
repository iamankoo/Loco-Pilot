"""POST/GET /api/v1/executions and the execution detail read APIs
(steps, tool-calls, artifacts) the dashboard consumes.

No arbitrary tool execution or raw-command endpoint here or anywhere in
the API — POST is the only way to trigger agent activity over HTTP, and
it only ever accepts a task description plus a project/workspace
reference. Every route here either creates/cancels an execution through
`execution_service`, or reads already-persisted data — nothing computes
or fabricates execution state.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.api.v1.dashboard_schemas import (
    AgentStepSummary,
    ArtifactSummary,
    ExecutionDetailResponse,
    ExecutionListResponse,
    ExecutionSummary,
    ToolCallListResponse,
    ToolCallSummary,
)
from backend.app.db.models.execution import ExecutionStatus
from backend.app.db.repositories.agent_steps import list_agent_steps_for_execution
from backend.app.db.repositories.artifacts import list_artifacts_for_execution
from backend.app.db.repositories.executions import count_executions, get_execution, list_executions
from backend.app.db.repositories.projects import create_project, get_project
from backend.app.db.repositories.tool_calls import count_tool_calls_for_execution, list_tool_calls_for_execution
from backend.app.db.session import get_db
from backend.app.services.execution_detail import elapsed_seconds, synthesize_execution_detail
from backend.app.services.execution_events import build_execution_events
from backend.app.services.execution_report import build_execution_report
from backend.app.services.execution_service import (
    ExecutionServiceError,
    cancel_execution,
    create_and_run_execution,
    run_execution,
)
from backend.app.services import runtime_service
from backend.app.services.workspace_discovery import discover_or_provision_workspace

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
    discovery = await discover_or_provision_workspace(
        db,
        task=payload.task,
        project_id=payload.project_id,
        workspace_path=payload.workspace_path,
        project_name=payload.project_name,
    )
    if discovery.outcome == "invalid":
        raise HTTPException(422, discovery.reason)
    if discovery.outcome == "not_found":
        raise HTTPException(404, discovery.reason)

    if discovery.project_id is not None:
        project_id = discovery.project_id
    else:
        project = await create_project(
            db, name=discovery.project_name or discovery.workspace_path, workspace_path=discovery.workspace_path
        )
        project_id = project.id

    try:
        execution = await create_and_run_execution(db, project_id=project_id, task=payload.task)
    except ExecutionServiceError as exc:
        raise HTTPException(422, str(exc)) from exc

    background_tasks.add_task(run_execution, execution.id)
    return ExecutionResponse.model_validate(execution)


@router.get("", response_model=ExecutionListResponse)
async def list_executions_endpoint(
    project_id: uuid.UUID | None = None,
    status: str | None = Query(default=None, description="Filter by execution status"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> ExecutionListResponse:
    if status is not None and status not in {s.value for s in ExecutionStatus}:
        raise HTTPException(422, f"Unknown status: {status!r}")

    executions = await list_executions(db, project_id=project_id, status=status, limit=limit, offset=offset)
    total = await count_executions(db, project_id=project_id, status=status)

    items = []
    for execution in executions:
        project = await get_project(db, execution.project_id)
        items.append(
            ExecutionSummary(
                id=execution.id,
                project_id=execution.project_id,
                project_name=project.name if project else None,
                task=execution.task,
                status=execution.status,
                current_agent=execution.current_agent,
                error_message=execution.error_message,
                created_at=execution.created_at,
                started_at=execution.started_at,
                completed_at=execution.completed_at,
                elapsed_seconds=elapsed_seconds(execution.started_at, execution.completed_at),
            )
        )

    return ExecutionListResponse(items=items, total=total, limit=limit, offset=offset)


@router.get("/{execution_id}", response_model=ExecutionDetailResponse)
async def get_execution_endpoint(
    execution_id: uuid.UUID, db: AsyncSession = Depends(get_db)
) -> ExecutionDetailResponse:
    execution = await get_execution(db, execution_id)
    if execution is None:
        raise HTTPException(404, "Execution not found.")

    project = await get_project(db, execution.project_id)
    steps = await list_agent_steps_for_execution(db, execution_id)
    synthesis = synthesize_execution_detail(steps)
    tool_call_count = await count_tool_calls_for_execution(db, execution_id)
    artifacts = await list_artifacts_for_execution(db, execution_id)

    step_errors = list(synthesis.step_errors)
    if execution.error_message and execution.error_message not in step_errors:
        step_errors.append(execution.error_message)

    return ExecutionDetailResponse(
        id=execution.id,
        project_id=execution.project_id,
        project_name=project.name if project else None,
        task=execution.task,
        status=execution.status,
        current_agent=synthesis.current_agent,
        retry_count=synthesis.retry_count,
        error_message=execution.error_message,
        created_at=execution.created_at,
        started_at=execution.started_at,
        completed_at=execution.completed_at,
        elapsed_seconds=elapsed_seconds(execution.started_at, execution.completed_at),
        plan=synthesis.plan,
        files_changed=synthesis.files_changed,
        test_results=synthesis.test_results,
        review_result=synthesis.review_result,
        tool_call_count=tool_call_count,
        artifact_count=len(artifacts),
        step_errors=step_errors,
    )


@router.get("/{execution_id}/steps", response_model=list[AgentStepSummary])
async def list_execution_steps_endpoint(
    execution_id: uuid.UUID, db: AsyncSession = Depends(get_db)
) -> list[AgentStepSummary]:
    execution = await get_execution(db, execution_id)
    if execution is None:
        raise HTTPException(404, "Execution not found.")

    steps = await list_agent_steps_for_execution(db, execution_id)
    result = []
    for step in steps:
        duration_ms = None
        if step.started_at and step.completed_at:
            duration_ms = int((step.completed_at - step.started_at).total_seconds() * 1000)
        metadata = step.output_metadata or {}
        result.append(
            AgentStepSummary(
                id=step.id,
                agent_name=step.agent_name,
                status=step.status,
                started_at=step.started_at,
                completed_at=step.completed_at,
                duration_ms=duration_ms,
                error_message=step.error_message,
                messages=metadata.get("messages") or [],
            )
        )
    return result


@router.get("/{execution_id}/tool-calls", response_model=ToolCallListResponse)
async def list_execution_tool_calls_endpoint(
    execution_id: uuid.UUID,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> ToolCallListResponse:
    execution = await get_execution(db, execution_id)
    if execution is None:
        raise HTTPException(404, "Execution not found.")

    tool_calls = await list_tool_calls_for_execution(db, execution_id, limit=limit, offset=offset)
    total = await count_tool_calls_for_execution(db, execution_id)
    items = [ToolCallSummary.model_validate(tc) for tc in tool_calls]
    return ToolCallListResponse(items=items, total=total, limit=limit, offset=offset)


@router.get("/{execution_id}/artifacts", response_model=list[ArtifactSummary])
async def list_execution_artifacts_endpoint(
    execution_id: uuid.UUID, db: AsyncSession = Depends(get_db)
) -> list[ArtifactSummary]:
    execution = await get_execution(db, execution_id)
    if execution is None:
        raise HTTPException(404, "Execution not found.")

    artifacts = await list_artifacts_for_execution(db, execution_id)
    return [
        ArtifactSummary(
            id=a.id, artifact_type=a.artifact_type, path=a.path, metadata=a.artifact_metadata, created_at=a.created_at
        )
        for a in artifacts
    ]


@router.get("/{execution_id}/report")
async def get_execution_report_endpoint(
    execution_id: uuid.UUID, db: AsyncSession = Depends(get_db)
) -> dict:
    """An evidence-based engineering report — see
    `backend.app.services.execution_report` for what "evidence-based" means
    here. Available for any execution regardless of terminal/non-terminal
    status; a still-running execution simply gets a partial report of
    whatever real progress has been persisted so far."""
    execution = await get_execution(db, execution_id)
    if execution is None:
        raise HTTPException(404, "Execution not found.")

    project = await get_project(db, execution.project_id)
    steps = await list_agent_steps_for_execution(db, execution_id)
    artifacts = await list_artifacts_for_execution(db, execution_id)

    return await build_execution_report(execution=execution, project=project, steps=steps, artifacts=artifacts)


@router.get("/{execution_id}/events")
async def get_execution_events_endpoint(
    execution_id: uuid.UUID, db: AsyncSession = Depends(get_db)
) -> dict:
    """A deterministic, ordered event stream plus execution metrics —
    reconstructed from persisted AgentStep/ToolCall rows (see
    `backend.app.services.execution_events`), not a live log tail."""
    execution = await get_execution(db, execution_id)
    if execution is None:
        raise HTTPException(404, "Execution not found.")

    steps = await list_agent_steps_for_execution(db, execution_id)
    # Bounded by the same execution-wide tool-call budget the graph itself
    # enforces (`settings.max_total_tool_calls`) — never an unbounded scan.
    tool_calls = await list_tool_calls_for_execution(db, execution_id, limit=10_000, offset=0)

    return build_execution_events(execution=execution, steps=steps, tool_calls=tool_calls)


@router.get("/{execution_id}/runtime")
async def get_execution_runtime_endpoint(
    execution_id: uuid.UUID, db: AsyncSession = Depends(get_db)
) -> dict:
    """Live runtime status — distinct from the `test_results.runtime_*`
    fields on the execution-detail response, which are a snapshot from
    when Tester verified the runtime. A runtime deliberately outlives its
    own execution (see `backend.app.services.runtime_service`) so an
    "Open in Browser" link the frontend shows after the run finishes isn't
    already dead the moment it appears — this endpoint reports whatever is
    ACTUALLY true right now (still running, expired, explicitly stopped,
    or never started), never a stale snapshot."""
    execution = await get_execution(db, execution_id)
    if execution is None:
        raise HTTPException(404, "Execution not found.")
    return await runtime_service.get_status(str(execution_id))


@router.post("/{execution_id}/runtime/stop", status_code=202)
async def stop_execution_runtime_endpoint(
    execution_id: uuid.UUID, db: AsyncSession = Depends(get_db)
) -> dict:
    execution = await get_execution(db, execution_id)
    if execution is None:
        raise HTTPException(404, "Execution not found.")
    stopped = await runtime_service.stop_runtime(str(execution_id))
    return {"stopped": stopped}


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
