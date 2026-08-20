from __future__ import annotations

import uuid

from backend.app.db.models.agent_step import AgentStepStatus
from backend.app.db.models.execution import ExecutionStatus
from backend.app.db.repositories.agent_steps import complete_agent_step, create_agent_step
from backend.app.db.repositories.artifacts import create_artifact
from backend.app.db.repositories.executions import create_execution, get_execution, update_execution_status
from backend.app.db.repositories.projects import create_project, get_project
from backend.app.db.repositories.tool_calls import create_tool_call


def _unique_name(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4()}"


async def test_create_project(db_session) -> None:
    project = await create_project(
        db_session, name=_unique_name("proj"), repo_url="https://example.invalid/repo.git"
    )
    assert project.id is not None
    fetched = await get_project(db_session, project.id)
    assert fetched is not None
    assert fetched.name == project.name


async def test_create_execution_and_relationship(db_session) -> None:
    project = await create_project(db_session, name=_unique_name("proj"))
    execution = await create_execution(db_session, project_id=project.id, task="Add a feature")
    assert execution.status == ExecutionStatus.PENDING.value
    fetched = await get_execution(db_session, execution.id)
    assert fetched is not None
    assert fetched.project_id == project.id


async def test_update_execution_status(db_session) -> None:
    project = await create_project(db_session, name=_unique_name("proj"))
    execution = await create_execution(db_session, project_id=project.id, task="Fix bug")
    updated = await update_execution_status(
        db_session,
        execution.id,
        status=ExecutionStatus.RUNNING,
        current_agent="planner",
        mark_started=True,
    )
    assert updated.status == ExecutionStatus.RUNNING.value
    assert updated.current_agent == "planner"
    assert updated.started_at is not None


async def test_agent_step_lifecycle(db_session) -> None:
    project = await create_project(db_session, name=_unique_name("proj"))
    execution = await create_execution(db_session, project_id=project.id, task="Fix bug")
    step = await create_agent_step(
        db_session, execution_id=execution.id, agent_name="planner", input_metadata={"goal": "x"}
    )
    assert step.status == AgentStepStatus.RUNNING.value

    completed = await complete_agent_step(
        db_session, step.id, status=AgentStepStatus.SUCCEEDED, output_metadata={"plan": "y"}
    )
    assert completed.status == AgentStepStatus.SUCCEEDED.value
    assert completed.completed_at is not None


async def test_tool_call_truncates_large_output(db_session) -> None:
    project = await create_project(db_session, name=_unique_name("proj"))
    execution = await create_execution(db_session, project_id=project.id, task="Fix bug")

    tool_call = await create_tool_call(
        db_session,
        execution_id=execution.id,
        tool_name="read_file",
        status="success",
        duration_ms=12,
        output={"content": "y" * 20_000},
    )
    assert len(tool_call.output["content"]) < 20_000
    assert "truncated" in tool_call.output["content"]


async def test_artifact_creation(db_session) -> None:
    project = await create_project(db_session, name=_unique_name("proj"))
    execution = await create_execution(db_session, project_id=project.id, task="Fix bug")

    artifact = await create_artifact(
        db_session, execution_id=execution.id, artifact_type="diff", path="diffs/1.patch"
    )
    assert artifact.id is not None
    assert artifact.artifact_type == "diff"


async def test_cascade_delete_removes_children(db_session) -> None:
    project = await create_project(db_session, name=_unique_name("proj"))
    execution = await create_execution(db_session, project_id=project.id, task="Fix bug")
    await create_agent_step(db_session, execution_id=execution.id, agent_name="planner")

    execution_row = await get_execution(db_session, execution.id)
    await db_session.delete(execution_row)
    await db_session.commit()

    assert await get_execution(db_session, execution.id) is None
