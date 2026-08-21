"""Phase 2.11: GET /api/v1/executions/{id}/report — an evidence-based
engineering report reconstructed entirely from persisted AgentStep/
Execution/Artifact data, covering successful, failed, debug-retry,
review-requested, cancelled, and incomplete/in-progress executions, plus
project isolation and secret-safety.
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


async def _seed_passed_execution(db_session):
    project = await create_project(db_session, name=f"proj-{uuid.uuid4()}", workspace_path="/tmp/whatever")
    execution = await create_execution(db_session, project_id=project.id, task="Fix the failing login test")
    await update_execution_status(db_session, execution.id, status=ExecutionStatus.RUNNING, mark_started=True)

    planner_step = await create_agent_step(db_session, execution_id=execution.id, agent_name="planner")
    await complete_agent_step(
        db_session, planner_step.id, status=AgentStepStatus.SUCCEEDED,
        output_metadata={
            "plan": {
                "objective": "fix login bug", "steps": ["inspect", "fix"], "testing_strategy": "pytest",
                "files_likely_involved": ["auth.py"], "assumptions": [], "risks": [], "expected_artifact_glob": None,
            },
        },
    )

    dev_step = await create_agent_step(db_session, execution_id=execution.id, agent_name="developer")
    await complete_agent_step(
        db_session, dev_step.id, status=AgentStepStatus.SUCCEEDED,
        output_metadata={"files_changed": [{"path": "auth.py", "change_type": "modified", "detail": "fixed"}]},
    )

    tester_step = await create_agent_step(db_session, execution_id=execution.id, agent_name="tester")
    await complete_agent_step(
        db_session, tester_step.id, status=AgentStepStatus.SUCCEEDED,
        output_metadata={
            "test_results": {
                "status": "passed", "commands": ["pytest"], "passed": 3, "failed": 0, "skipped": 0,
                "errors": [], "summary": "3 passed",
            },
        },
    )

    reviewer_step = await create_agent_step(db_session, execution_id=execution.id, agent_name="reviewer")
    await complete_agent_step(
        db_session, reviewer_step.id, status=AgentStepStatus.SUCCEEDED,
        output_metadata={
            "review_result": {
                "verdict": "approved", "summary": "looks good", "issues": [], "regressions_observed": [],
                "security_issues": [], "recommendations": [], "risk": "low", "files_reviewed": 1,
                "tests_evaluated": 3, "attempt_number": 1,
            },
            "review_attempts": [{"verdict": "approved", "summary": "looks good"}],
        },
    )

    await update_execution_status(db_session, execution.id, status=ExecutionStatus.PASSED, mark_completed=True)
    await create_artifact(
        db_session, execution_id=execution.id, artifact_type="python-wheel", path="dist/app.whl",
        metadata={"size_bytes": 1234},
    )
    return project, execution


async def test_report_for_a_successful_execution_covers_every_section(client: AsyncClient, db_session) -> None:
    _project, execution = await _seed_passed_execution(db_session)

    response = await client.get(f"/api/v1/executions/{execution.id}/report")
    assert response.status_code == 200
    report = response.json()

    assert report["execution"]["status"] == "passed"
    assert report["execution"]["task"] == "Fix the failing login test"
    assert report["plan"]["objective"] == "fix login bug"
    assert report["changes"]["modified"] == ["auth.py"]
    assert report["changes"]["total_real_changes"] == 1
    assert report["tests"]["status"] == "passed"
    assert report["debugging"]["attempt_count"] == 0
    assert report["review"]["verdict"] == "approved"
    assert len(report["artifacts"]) == 1
    assert report["final"]["status"] == "passed"
    assert "successfully" in report["final"]["reason"].lower() or "passed" in report["final"]["reason"].lower()


async def test_report_for_a_failed_execution_includes_error_and_recommendation(
    client: AsyncClient, db_session
) -> None:
    project = await create_project(db_session, name=f"proj-{uuid.uuid4()}", workspace_path="/tmp/x")
    execution = await create_execution(db_session, project_id=project.id, task="Add a new endpoint")
    await update_execution_status(db_session, execution.id, status=ExecutionStatus.RUNNING, mark_started=True)

    planner_step = await create_agent_step(db_session, execution_id=execution.id, agent_name="planner")
    await complete_agent_step(
        db_session, planner_step.id, status=AgentStepStatus.FAILED,
        error_message="LLM request failed: 429 quota exceeded", output_metadata={},
    )

    await update_execution_status(
        db_session, execution.id, status=ExecutionStatus.ERROR,
        error_message="LLM request failed: 429 quota exceeded", mark_completed=True,
    )

    response = await client.get(f"/api/v1/executions/{execution.id}/report")
    assert response.status_code == 200
    report = response.json()

    assert report["execution"]["status"] == "error"
    assert "429 quota exceeded" in report["final"]["reason"]
    assert any("429 quota exceeded" in e for e in report["final"]["step_errors"])
    assert "Inspect" in report["final"]["recommended_next_action"]


async def test_report_includes_full_debug_retry_history(client: AsyncClient, db_session) -> None:
    project = await create_project(db_session, name=f"proj-{uuid.uuid4()}", workspace_path="/tmp/x")
    execution = await create_execution(db_session, project_id=project.id, task="fix flaky test")
    await update_execution_status(db_session, execution.id, status=ExecutionStatus.RUNNING, mark_started=True)

    debugger_step = await create_agent_step(db_session, execution_id=execution.id, agent_name="debugger")
    await complete_agent_step(
        db_session, debugger_step.id, status=AgentStepStatus.SUCCEEDED,
        output_metadata={
            "debug_attempts": [
                {
                    "root_cause": "off by one", "proposed_fix": "adjust range", "confidence": "high",
                    "failure_class": "assertion_failure", "attempt_number": 1, "status": "diagnosed",
                    "files_inspected": ["calc.py"],
                },
            ],
        },
    )

    await update_execution_status(db_session, execution.id, status=ExecutionStatus.NEEDS_REVIEW, mark_completed=True)

    response = await client.get(f"/api/v1/executions/{execution.id}/report")
    report = response.json()
    assert report["debugging"]["attempt_count"] == 1
    assert report["debugging"]["attempts"][0]["root_cause"] == "off by one"
    assert report["debugging"]["final_status"] == "diagnosed"


async def test_report_for_a_review_requested_execution(client: AsyncClient, db_session) -> None:
    project = await create_project(db_session, name=f"proj-{uuid.uuid4()}", workspace_path="/tmp/x")
    execution = await create_execution(db_session, project_id=project.id, task="refactor module")
    await update_execution_status(db_session, execution.id, status=ExecutionStatus.RUNNING, mark_started=True)

    reviewer_step = await create_agent_step(db_session, execution_id=execution.id, agent_name="reviewer")
    await complete_agent_step(
        db_session, reviewer_step.id, status=AgentStepStatus.SUCCEEDED,
        output_metadata={
            "review_result": {
                "verdict": "changes_required", "summary": "missing tests", "issues": ["no test coverage"],
                "regressions_observed": [], "security_issues": [], "recommendations": ["add tests"],
                "risk": "medium", "files_reviewed": 2, "tests_evaluated": 0, "attempt_number": 1,
            },
            "review_attempts": [{"verdict": "changes_required", "summary": "missing tests"}],
        },
    )
    await update_execution_status(db_session, execution.id, status=ExecutionStatus.NEEDS_REVIEW, mark_completed=True)

    response = await client.get(f"/api/v1/executions/{execution.id}/report")
    report = response.json()
    assert report["review"]["verdict"] == "changes_required"
    assert "add tests" in report["review"]["recommendations"]
    assert "Reviewer requested changes" in report["final"]["recommended_next_action"]


async def test_report_for_a_cancelled_execution(client: AsyncClient, db_session) -> None:
    project = await create_project(db_session, name=f"proj-{uuid.uuid4()}", workspace_path="/tmp/x")
    execution = await create_execution(db_session, project_id=project.id, task="long running task")
    await update_execution_status(db_session, execution.id, status=ExecutionStatus.RUNNING, mark_started=True)
    await update_execution_status(db_session, execution.id, status=ExecutionStatus.CANCELLED, mark_completed=True)

    response = await client.get(f"/api/v1/executions/{execution.id}/report")
    report = response.json()
    assert report["execution"]["status"] == "cancelled"
    assert report["final"]["status"] == "cancelled"
    assert "cancelled" in report["final"]["recommended_next_action"].lower()


async def test_report_for_an_incomplete_in_progress_execution_is_partial_but_present(
    client: AsyncClient, db_session
) -> None:
    project = await create_project(db_session, name=f"proj-{uuid.uuid4()}", workspace_path="/tmp/x")
    execution = await create_execution(db_session, project_id=project.id, task="in progress task")
    await update_execution_status(db_session, execution.id, status=ExecutionStatus.RUNNING, mark_started=True)
    await create_agent_step(db_session, execution_id=execution.id, agent_name="developer")  # never completed

    response = await client.get(f"/api/v1/executions/{execution.id}/report")
    assert response.status_code == 200
    report = response.json()
    assert report["execution"]["status"] == "running"
    assert report["execution"]["current_agent"] == "developer"
    assert report["plan"] is None
    assert report["tests"] is None


async def test_report_404_for_unknown_execution(client: AsyncClient, db_session) -> None:
    response = await client.get(f"/api/v1/executions/{uuid.uuid4()}/report")
    assert response.status_code == 404


async def test_report_never_leaks_across_projects(client: AsyncClient, db_session) -> None:
    _project_a, execution_a = await _seed_passed_execution(db_session)
    project_b = await create_project(db_session, name=f"proj-{uuid.uuid4()}")
    execution_b = await create_execution(db_session, project_id=project_b.id, task="unrelated task")

    response = await client.get(f"/api/v1/executions/{execution_b.id}/report")
    report = response.json()
    assert report["execution"]["id"] == str(execution_b.id)
    assert report["execution"]["task"] == "unrelated task"
    assert report["plan"] is None  # never execution_a's plan


async def test_report_contains_no_api_keys_or_secrets(client: AsyncClient, db_session, monkeypatch) -> None:
    monkeypatch.setenv("LLM_API_KEY", "sk-super-secret-value-should-never-leak")
    project = await create_project(db_session, name=f"proj-{uuid.uuid4()}", workspace_path="/tmp/x")
    execution = await create_execution(db_session, project_id=project.id, task="task with a secret nearby")
    await update_execution_status(db_session, execution.id, status=ExecutionStatus.RUNNING, mark_started=True)
    await update_execution_status(
        db_session, execution.id, status=ExecutionStatus.ERROR,
        error_message="failed, unrelated to any key", mark_completed=True,
    )

    response = await client.get(f"/api/v1/executions/{execution.id}/report")
    assert "sk-super-secret-value-should-never-leak" not in response.text
