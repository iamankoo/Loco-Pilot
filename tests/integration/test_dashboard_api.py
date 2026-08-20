"""Tests for the dashboard's read APIs: /projects, /executions (list +
detail), /executions/{id}/{steps,tool-calls,artifacts}.

Seeds realistic persisted data directly (the exact shape
`agents.graph.make_agent_node` writes to `AgentStep.output_metadata`)
rather than running the full graph — the graph's own correctness is
already covered by Phase 1.3-1.5 tests; these tests are about the read
side faithfully reconstructing and scoping that persisted data.
"""

from __future__ import annotations

import uuid

from httpx import AsyncClient

from backend.app.db.models.agent_step import AgentStepStatus
from backend.app.db.models.execution import ExecutionStatus
from backend.app.db.repositories.agent_steps import complete_agent_step, create_agent_step
from backend.app.db.repositories.artifacts import create_artifact
from backend.app.db.repositories.executions import create_execution, update_execution_status
from backend.app.db.repositories.projects import create_project
from backend.app.db.repositories.tool_calls import create_tool_call


async def _seed_full_execution(db_session):
    project = await create_project(db_session, name=f"proj-{uuid.uuid4()}", workspace_path="/tmp/whatever")
    execution = await create_execution(db_session, project_id=project.id, task="Fix the failing test")
    await update_execution_status(db_session, execution.id, status=ExecutionStatus.RUNNING, mark_started=True)

    planner_step = await create_agent_step(
        db_session, execution_id=execution.id, agent_name="planner", input_metadata={"retry_count": 0}
    )
    await complete_agent_step(
        db_session,
        planner_step.id,
        status=AgentStepStatus.SUCCEEDED,
        output_metadata={
            "plan": {
                "objective": "fix bug",
                "steps": ["inspect", "fix"],
                "testing_strategy": "pytest",
                "files_likely_involved": ["a.py"],
                "assumptions": [],
                "risks": [],
                "expected_artifact_glob": None,
            },
            "messages": ["Planner: produced a plan with 2 step(s)."],
        },
    )

    dev_step = await create_agent_step(
        db_session, execution_id=execution.id, agent_name="developer", input_metadata={"retry_count": 0}
    )
    await complete_agent_step(
        db_session,
        dev_step.id,
        status=AgentStepStatus.SUCCEEDED,
        output_metadata={
            "files_changed": [{"path": "a.py", "change_type": "modified", "detail": "edit_file applied"}],
            "messages": ["Developer: fixed the bug (1 change(s) applied, 0 failed, 1 tool call(s))."],
        },
    )
    await create_tool_call(
        db_session,
        execution_id=execution.id,
        agent_step_id=dev_step.id,
        tool_name="edit_file",
        status="success",
        duration_ms=12,
        input={"path": "a.py", "old_string": "x", "new_string": "y"},
        output={"path": "a.py", "replaced": True, "occurrences": 1},
    )

    tester_step = await create_agent_step(
        db_session, execution_id=execution.id, agent_name="tester", input_metadata={"retry_count": 0}
    )
    await complete_agent_step(
        db_session,
        tester_step.id,
        status=AgentStepStatus.SUCCEEDED,
        output_metadata={
            "test_results": {
                "status": "passed",
                "commands": ["python -m pytest"],
                "passed": 3,
                "failed": 0,
                "errors": [],
                "summary": "3 passed",
            },
            "messages": ["Tester: 3 passed"],
        },
    )
    await create_tool_call(
        db_session,
        execution_id=execution.id,
        agent_step_id=tester_step.id,
        tool_name="execute_terminal_command",
        status="success",
        duration_ms=1500,
        input={"command": ["python", "-m", "pytest"]},
        output={"exit_code": 0, "stdout": "3 passed", "stderr": ""},
    )

    reviewer_step = await create_agent_step(
        db_session, execution_id=execution.id, agent_name="reviewer", input_metadata={"retry_count": 0}
    )
    await complete_agent_step(
        db_session,
        reviewer_step.id,
        status=AgentStepStatus.SUCCEEDED,
        output_metadata={
            "review_result": {"verdict": "approved", "summary": "looks good", "issues": [], "regressions_observed": []},
            "messages": ["Reviewer: approved — looks good"],
        },
    )

    await update_execution_status(db_session, execution.id, status=ExecutionStatus.PASSED, mark_completed=True)
    await create_artifact(
        db_session, execution_id=execution.id, artifact_type="python-wheel", path="dist/app.whl",
        metadata={"size_bytes": 1234},
    )

    return project, execution


async def test_list_projects_includes_execution_stats(client: AsyncClient, db_session) -> None:
    project, _execution = await _seed_full_execution(db_session)

    response = await client.get("/api/v1/projects")
    assert response.status_code == 200
    body = response.json()
    matching = next(p for p in body["items"] if p["id"] == str(project.id))
    assert matching["last_execution_status"] == "passed"
    assert matching["execution_counts"].get("passed") == 1


async def test_list_projects_pagination(client: AsyncClient, db_session) -> None:
    for _ in range(3):
        await create_project(db_session, name=f"proj-{uuid.uuid4()}")

    response = await client.get("/api/v1/projects", params={"limit": 1, "offset": 0})
    body = response.json()
    assert len(body["items"]) == 1
    assert body["total"] >= 3


async def test_get_project_detail_includes_recent_executions(client: AsyncClient, db_session) -> None:
    project, execution = await _seed_full_execution(db_session)

    response = await client.get(f"/api/v1/projects/{project.id}")
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(project.id)
    assert any(e["id"] == str(execution.id) for e in body["recent_executions"])


async def test_get_project_detail_404_for_unknown_id(client: AsyncClient, db_session) -> None:
    response = await client.get(f"/api/v1/projects/{uuid.uuid4()}")
    assert response.status_code == 404


async def test_list_executions_filters_by_project(client: AsyncClient, db_session) -> None:
    project_a, execution_a = await _seed_full_execution(db_session)
    project_b = await create_project(db_session, name=f"proj-{uuid.uuid4()}")
    execution_b = await create_execution(db_session, project_id=project_b.id, task="other task")

    response = await client.get("/api/v1/executions", params={"project_id": str(project_a.id)})
    assert response.status_code == 200
    ids = {e["id"] for e in response.json()["items"]}
    assert str(execution_a.id) in ids
    assert str(execution_b.id) not in ids


async def test_list_executions_filters_by_status(client: AsyncClient, db_session) -> None:
    project, _execution = await _seed_full_execution(db_session)
    other_project = await create_project(db_session, name=f"proj-{uuid.uuid4()}")
    await create_execution(db_session, project_id=other_project.id, task="still pending")

    response = await client.get("/api/v1/executions", params={"status": "passed"})
    body = response.json()
    assert len(body["items"]) >= 1
    assert all(e["status"] == "passed" for e in body["items"])


async def test_list_executions_rejects_unknown_status(client: AsyncClient, db_session) -> None:
    response = await client.get("/api/v1/executions", params={"status": "not-a-real-status"})
    assert response.status_code == 422


async def test_list_executions_pagination(client: AsyncClient, db_session) -> None:
    project = await create_project(db_session, name=f"proj-{uuid.uuid4()}")
    for i in range(5):
        await create_execution(db_session, project_id=project.id, task=f"task {i}")

    response = await client.get(
        "/api/v1/executions", params={"project_id": str(project.id), "limit": 2, "offset": 0}
    )
    body = response.json()
    assert len(body["items"]) == 2
    assert body["total"] == 5


async def test_no_cross_project_execution_leakage(client: AsyncClient, db_session) -> None:
    project_a, execution_a = await _seed_full_execution(db_session)
    project_b = await create_project(db_session, name=f"proj-{uuid.uuid4()}")
    execution_b = await create_execution(db_session, project_id=project_b.id, task="unrelated")

    response = await client.get("/api/v1/executions", params={"project_id": str(project_b.id)})
    ids = {e["id"] for e in response.json()["items"]}
    assert ids == {str(execution_b.id)}
    assert str(execution_a.id) not in ids


async def test_get_execution_detail_synthesizes_plan_files_tests_review(
    client: AsyncClient, db_session
) -> None:
    _project, execution = await _seed_full_execution(db_session)

    response = await client.get(f"/api/v1/executions/{execution.id}")
    assert response.status_code == 200
    body = response.json()
    assert body["plan"]["objective"] == "fix bug"
    assert len(body["files_changed"]) == 1
    assert body["files_changed"][0]["path"] == "a.py"
    assert body["test_results"]["status"] == "passed"
    assert body["review_result"]["verdict"] == "approved"
    assert body["tool_call_count"] == 2
    assert body["artifact_count"] == 1
    assert body["status"] == "passed"
    assert body["current_agent"] == "reviewer"


async def test_get_execution_detail_404_for_unknown_id(client: AsyncClient, db_session) -> None:
    response = await client.get(f"/api/v1/executions/{uuid.uuid4()}")
    assert response.status_code == 404


async def test_execution_detail_current_agent_reflects_in_progress_step(
    client: AsyncClient, db_session
) -> None:
    project = await create_project(db_session, name=f"proj-{uuid.uuid4()}", workspace_path="/tmp/x")
    execution = await create_execution(db_session, project_id=project.id, task="in progress task")
    await update_execution_status(db_session, execution.id, status=ExecutionStatus.RUNNING, mark_started=True)
    # a step that's been created but not completed = currently running
    await create_agent_step(
        db_session, execution_id=execution.id, agent_name="developer", input_metadata={"retry_count": 0}
    )

    response = await client.get(f"/api/v1/executions/{execution.id}")
    body = response.json()
    assert body["current_agent"] == "developer"
    assert body["status"] == "running"


async def test_list_execution_steps_returns_messages_in_order(client: AsyncClient, db_session) -> None:
    _project, execution = await _seed_full_execution(db_session)

    response = await client.get(f"/api/v1/executions/{execution.id}/steps")
    assert response.status_code == 200
    body = response.json()
    assert [s["agent_name"] for s in body] == ["planner", "developer", "tester", "reviewer"]
    assert "Planner: produced a plan" in body[0]["messages"][0]
    assert all(s["duration_ms"] is not None for s in body)


async def test_list_execution_steps_404_for_unknown_execution(client: AsyncClient, db_session) -> None:
    response = await client.get(f"/api/v1/executions/{uuid.uuid4()}/steps")
    assert response.status_code == 404


async def test_list_execution_tool_calls(client: AsyncClient, db_session) -> None:
    _project, execution = await _seed_full_execution(db_session)

    response = await client.get(f"/api/v1/executions/{execution.id}/tool-calls")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    tool_names = {tc["tool_name"] for tc in body["items"]}
    assert tool_names == {"edit_file", "execute_terminal_command"}


async def test_list_execution_tool_calls_pagination(client: AsyncClient, db_session) -> None:
    _project, execution = await _seed_full_execution(db_session)

    response = await client.get(
        f"/api/v1/executions/{execution.id}/tool-calls", params={"limit": 1, "offset": 0}
    )
    body = response.json()
    assert len(body["items"]) == 1
    assert body["total"] == 2


async def test_list_execution_tool_calls_404_for_unknown_execution(client: AsyncClient, db_session) -> None:
    response = await client.get(f"/api/v1/executions/{uuid.uuid4()}/tool-calls")
    assert response.status_code == 404


async def test_list_execution_artifacts(client: AsyncClient, db_session) -> None:
    _project, execution = await _seed_full_execution(db_session)

    response = await client.get(f"/api/v1/executions/{execution.id}/artifacts")
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["path"] == "dist/app.whl"
    assert body[0]["artifact_type"] == "python-wheel"


async def test_list_execution_artifacts_404_for_unknown_execution(client: AsyncClient, db_session) -> None:
    response = await client.get(f"/api/v1/executions/{uuid.uuid4()}/artifacts")
    assert response.status_code == 404
