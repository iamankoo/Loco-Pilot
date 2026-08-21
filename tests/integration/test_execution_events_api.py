"""Phase 2.12: GET /api/v1/executions/{id}/events — a deterministic,
ordered event stream and execution metrics reconstructed from persisted
AgentStep/ToolCall data, without relying on an LLM's own account of what
happened or manual raw-log inspection.
"""

from __future__ import annotations

import uuid

from httpx import AsyncClient

from backend.app.db.models.agent_step import AgentStepStatus
from backend.app.db.models.execution import ExecutionStatus
from backend.app.db.repositories.agent_steps import complete_agent_step, create_agent_step
from backend.app.db.repositories.executions import create_execution, update_execution_status
from backend.app.db.repositories.projects import create_project
from backend.app.db.repositories.tool_calls import create_tool_call


async def test_events_reconstruct_full_lifecycle_in_order(client: AsyncClient, db_session) -> None:
    project = await create_project(db_session, name=f"proj-{uuid.uuid4()}", workspace_path="/tmp/x")
    execution = await create_execution(db_session, project_id=project.id, task="fix the bug")
    await update_execution_status(db_session, execution.id, status=ExecutionStatus.RUNNING, mark_started=True)

    planner_step = await create_agent_step(db_session, execution_id=execution.id, agent_name="planner")
    await complete_agent_step(db_session, planner_step.id, status=AgentStepStatus.SUCCEEDED, output_metadata={})

    dev_step = await create_agent_step(db_session, execution_id=execution.id, agent_name="developer")
    await create_tool_call(
        db_session, execution_id=execution.id, agent_step_id=dev_step.id, tool_name="edit_file",
        status="success", duration_ms=15, input={}, output={},
    )
    await complete_agent_step(db_session, dev_step.id, status=AgentStepStatus.SUCCEEDED, output_metadata={})

    tester_step = await create_agent_step(db_session, execution_id=execution.id, agent_name="tester")
    await complete_agent_step(
        db_session, tester_step.id, status=AgentStepStatus.SUCCEEDED,
        output_metadata={"test_results": {"status": "failed", "summary": "1 failed"}},
    )

    await update_execution_status(
        db_session, execution.id, status=ExecutionStatus.NEEDS_REVIEW, mark_completed=True
    )

    response = await client.get(f"/api/v1/executions/{execution.id}/events")
    assert response.status_code == 200
    body = response.json()
    event_names = [e["event"] for e in body["events"]]

    assert event_names[0] == "execution_started"
    assert "planner_started" in event_names
    assert "planner_completed" in event_names
    assert event_names.index("planner_started") < event_names.index("planner_completed")
    assert "tool_call_completed" in event_names
    assert "test_failed" in event_names
    assert event_names[-1] == "execution_completed"
    # seq is a stable, gap-free ordinal matching final sorted order.
    assert [e["seq"] for e in body["events"]] == list(range(len(body["events"])))


async def test_tool_call_failure_is_reported_with_bounded_error(client: AsyncClient, db_session) -> None:
    project = await create_project(db_session, name=f"proj-{uuid.uuid4()}", workspace_path="/tmp/x")
    execution = await create_execution(db_session, project_id=project.id, task="task")
    await update_execution_status(db_session, execution.id, status=ExecutionStatus.RUNNING, mark_started=True)

    dev_step = await create_agent_step(db_session, execution_id=execution.id, agent_name="developer")
    await create_tool_call(
        db_session, execution_id=execution.id, agent_step_id=dev_step.id, tool_name="write_file",
        status="error", duration_ms=5, input={}, output=None, error_message="Path escapes workspace boundary",
    )
    await complete_agent_step(db_session, dev_step.id, status=AgentStepStatus.SUCCEEDED, output_metadata={})
    await update_execution_status(db_session, execution.id, status=ExecutionStatus.ERROR, mark_completed=True)

    response = await client.get(f"/api/v1/executions/{execution.id}/events")
    body = response.json()
    failed = next(e for e in body["events"] if e["event"] == "tool_call_failed")
    assert failed["tool"] == "write_file"
    assert failed["error"] == "Path escapes workspace boundary"


async def test_review_changes_required_emits_review_changes_requested(client: AsyncClient, db_session) -> None:
    project = await create_project(db_session, name=f"proj-{uuid.uuid4()}", workspace_path="/tmp/x")
    execution = await create_execution(db_session, project_id=project.id, task="task")
    await update_execution_status(db_session, execution.id, status=ExecutionStatus.RUNNING, mark_started=True)

    reviewer_step = await create_agent_step(db_session, execution_id=execution.id, agent_name="reviewer")
    await complete_agent_step(
        db_session, reviewer_step.id, status=AgentStepStatus.SUCCEEDED,
        output_metadata={"review_result": {"verdict": "changes_required", "summary": "needs work"}},
    )
    await update_execution_status(db_session, execution.id, status=ExecutionStatus.NEEDS_REVIEW, mark_completed=True)

    response = await client.get(f"/api/v1/executions/{execution.id}/events")
    event_names = [e["event"] for e in response.json()["events"]]
    assert "review_changes_requested" in event_names


async def test_agent_failure_is_classified(client: AsyncClient, db_session) -> None:
    project = await create_project(db_session, name=f"proj-{uuid.uuid4()}", workspace_path="/tmp/x")
    execution = await create_execution(db_session, project_id=project.id, task="task")
    await update_execution_status(db_session, execution.id, status=ExecutionStatus.RUNNING, mark_started=True)

    planner_step = await create_agent_step(db_session, execution_id=execution.id, agent_name="planner")
    await complete_agent_step(
        db_session, planner_step.id, status=AgentStepStatus.FAILED,
        error_message="401 Incorrect API key provided", output_metadata={},
    )
    await update_execution_status(
        db_session, execution.id, status=ExecutionStatus.ERROR,
        error_message="401 Incorrect API key provided", mark_completed=True,
    )

    response = await client.get(f"/api/v1/executions/{execution.id}/events")
    body = response.json()
    failed = next(e for e in body["events"] if e["event"] == "planner_failed")
    assert failed["error_class"] == "llm_auth_error"
    terminal = body["events"][-1]
    assert terminal["event"] == "execution_failed"
    assert terminal["error_class"] == "llm_auth_error"


async def test_retry_started_event_when_retry_count_is_nonzero(client: AsyncClient, db_session) -> None:
    project = await create_project(db_session, name=f"proj-{uuid.uuid4()}", workspace_path="/tmp/x")
    execution = await create_execution(db_session, project_id=project.id, task="task")
    await update_execution_status(db_session, execution.id, status=ExecutionStatus.RUNNING, mark_started=True)

    debugger_step = await create_agent_step(
        db_session, execution_id=execution.id, agent_name="debugger", input_metadata={"retry_count": 1}
    )
    await complete_agent_step(db_session, debugger_step.id, status=AgentStepStatus.SUCCEEDED, output_metadata={})
    await update_execution_status(db_session, execution.id, status=ExecutionStatus.NEEDS_REVIEW, mark_completed=True)

    response = await client.get(f"/api/v1/executions/{execution.id}/events")
    event_names = [e["event"] for e in response.json()["events"]]
    assert "retry_started" in event_names


async def test_metrics_reflect_real_tool_and_debug_review_counts(client: AsyncClient, db_session) -> None:
    project = await create_project(db_session, name=f"proj-{uuid.uuid4()}", workspace_path="/tmp/x")
    execution = await create_execution(db_session, project_id=project.id, task="task")
    await update_execution_status(db_session, execution.id, status=ExecutionStatus.RUNNING, mark_started=True)

    debugger_step = await create_agent_step(db_session, execution_id=execution.id, agent_name="debugger")
    await complete_agent_step(
        db_session, debugger_step.id, status=AgentStepStatus.SUCCEEDED,
        output_metadata={"debug_attempts": [{"attempt_number": 1}, {"attempt_number": 2}]},
    )
    await create_tool_call(
        db_session, execution_id=execution.id, agent_step_id=debugger_step.id, tool_name="read_file",
        status="success", duration_ms=3, input={}, output={},
    )
    await create_tool_call(
        db_session, execution_id=execution.id, agent_step_id=debugger_step.id, tool_name="read_file",
        status="error", duration_ms=3, input={}, output=None, error_message="not found",
    )

    tester_step = await create_agent_step(db_session, execution_id=execution.id, agent_name="tester")
    await complete_agent_step(db_session, tester_step.id, status=AgentStepStatus.SUCCEEDED, output_metadata={})

    await update_execution_status(db_session, execution.id, status=ExecutionStatus.NEEDS_REVIEW, mark_completed=True)

    response = await client.get(f"/api/v1/executions/{execution.id}/events")
    metrics = response.json()["metrics"]
    assert metrics["tool_call_count"] == 2
    assert metrics["tool_call_failures"] == 1
    assert metrics["test_run_count"] == 1
    assert metrics["debug_attempt_count"] == 2
    assert "debugger" in metrics["per_agent_duration_ms"]


async def test_events_404_for_unknown_execution(client: AsyncClient, db_session) -> None:
    response = await client.get(f"/api/v1/executions/{uuid.uuid4()}/events")
    assert response.status_code == 404


async def test_events_never_leak_across_projects(client: AsyncClient, db_session) -> None:
    project_a = await create_project(db_session, name=f"proj-{uuid.uuid4()}", workspace_path="/tmp/a")
    execution_a = await create_execution(db_session, project_id=project_a.id, task="task a")
    step_a = await create_agent_step(db_session, execution_id=execution_a.id, agent_name="planner")
    await complete_agent_step(db_session, step_a.id, status=AgentStepStatus.SUCCEEDED, output_metadata={})

    project_b = await create_project(db_session, name=f"proj-{uuid.uuid4()}", workspace_path="/tmp/b")
    execution_b = await create_execution(db_session, project_id=project_b.id, task="task b")

    response = await client.get(f"/api/v1/executions/{execution_b.id}/events")
    body = response.json()
    assert all(e.get("event") != "planner_started" for e in body["events"])


async def test_events_contain_no_secrets(client: AsyncClient, db_session, monkeypatch) -> None:
    monkeypatch.setenv("LLM_API_KEY", "sk-should-never-appear-anywhere")
    project = await create_project(db_session, name=f"proj-{uuid.uuid4()}", workspace_path="/tmp/x")
    execution = await create_execution(db_session, project_id=project.id, task="task")
    await update_execution_status(db_session, execution.id, status=ExecutionStatus.RUNNING, mark_started=True)
    await update_execution_status(
        db_session, execution.id, status=ExecutionStatus.ERROR,
        error_message="unrelated failure", mark_completed=True,
    )

    response = await client.get(f"/api/v1/executions/{execution.id}/events")
    assert "sk-should-never-appear-anywhere" not in response.text
