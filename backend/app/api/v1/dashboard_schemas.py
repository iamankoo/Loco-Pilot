"""Response schemas for the dashboard's read APIs.

Deliberately separate from `agents.schemas` — these are the API's public
contract (stable field names/shapes for the frontend), not the internal
LangGraph state schemas, even though their shape is currently similar.
Everything here is read from already-persisted, already-scrubbed data;
none of it is computed on the frontend.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel


class PlanSummary(BaseModel):
    objective: str | None = None
    assumptions: list[str] = []
    files_likely_involved: list[str] = []
    steps: list[str] = []
    testing_strategy: str | None = None
    risks: list[str] = []
    expected_artifact_glob: str | None = None


class FileChangeSummary(BaseModel):
    path: str
    change_type: str
    detail: str | None = None


class TestResultSummary(BaseModel):
    status: str
    commands: list[str] = []
    passed: int = 0
    failed: int = 0
    errors: list[str] = []
    summary: str | None = None
    verification_kind: str = "automated_tests"
    runtime_url: str | None = None
    runtime_status: str | None = None


class ReviewResultSummary(BaseModel):
    verdict: str
    summary: str | None = None
    issues: list[str] = []
    regressions_observed: list[str] = []


class ExecutionSummary(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    project_name: str | None = None
    task: str
    status: str
    current_agent: str | None = None
    retry_count: int = 0
    error_message: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    elapsed_seconds: float | None = None

    model_config = {"from_attributes": True}


class ExecutionListResponse(BaseModel):
    items: list[ExecutionSummary]
    total: int
    limit: int
    offset: int


class ExecutionDetailResponse(ExecutionSummary):
    plan: PlanSummary | None = None
    files_changed: list[FileChangeSummary] = []
    test_results: TestResultSummary | None = None
    review_result: ReviewResultSummary | None = None
    tool_call_count: int = 0
    artifact_count: int = 0
    step_errors: list[str] = []


class AgentStepSummary(BaseModel):
    id: uuid.UUID
    agent_name: str
    status: str
    started_at: datetime | None = None
    completed_at: datetime | None = None
    duration_ms: int | None = None
    error_message: str | None = None
    messages: list[str] = []


class ToolCallSummary(BaseModel):
    id: uuid.UUID
    agent_step_id: uuid.UUID | None = None
    tool_name: str
    status: str
    input: dict | None = None
    output: dict | None = None
    error_message: str | None = None
    duration_ms: int | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class ToolCallListResponse(BaseModel):
    items: list[ToolCallSummary]
    total: int
    limit: int
    offset: int


class ArtifactSummary(BaseModel):
    id: uuid.UUID
    artifact_type: str
    path: str
    metadata: dict | None = None
    created_at: datetime


class ProjectSummary(BaseModel):
    id: uuid.UUID
    name: str
    repo_url: str | None = None
    workspace_path: str | None = None
    created_at: datetime
    updated_at: datetime
    last_execution_status: str | None = None
    last_execution_at: datetime | None = None
    execution_counts: dict[str, int] = {}


class ProjectListResponse(BaseModel):
    items: list[ProjectSummary]
    total: int
    limit: int
    offset: int


class ProjectDetailResponse(ProjectSummary):
    recent_executions: list[ExecutionSummary] = []
