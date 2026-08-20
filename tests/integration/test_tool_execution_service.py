from __future__ import annotations

import uuid

from sqlalchemy import select

from backend.app.db.models.tool_call import ToolCall
from backend.app.db.repositories.executions import create_execution
from backend.app.db.repositories.projects import create_project
from backend.app.services.tool_execution import execute_tool
from tools.base import ToolContext
from tools.registry import ToolNotFoundError, build_default_registry
from tools.workspace import Workspace


async def test_execute_tool_persists_successful_tool_call(db_session, tmp_workspace: Workspace) -> None:
    project = await create_project(db_session, name=f"proj-{uuid.uuid4()}")
    execution = await create_execution(db_session, project_id=project.id, task="test task")

    registry = build_default_registry()
    context = ToolContext(workspace=tmp_workspace, execution_id=str(execution.id))

    result = await execute_tool(registry, "write_file", {"path": "a.txt", "content": "hello"}, context, db=db_session)
    assert result.status == "success"

    rows = (
        (await db_session.execute(select(ToolCall).where(ToolCall.execution_id == execution.id))).scalars().all()
    )
    assert len(rows) == 1
    assert rows[0].tool_name == "write_file"
    assert rows[0].status == "success"


async def test_execute_tool_persists_failed_tool_call(db_session, tmp_workspace: Workspace) -> None:
    project = await create_project(db_session, name=f"proj-{uuid.uuid4()}")
    execution = await create_execution(db_session, project_id=project.id, task="test task")

    registry = build_default_registry()
    context = ToolContext(workspace=tmp_workspace, execution_id=str(execution.id))

    result = await execute_tool(registry, "read_file", {"path": "missing.txt"}, context, db=db_session)
    assert result.status == "error"
    assert result.error is not None

    rows = (
        (await db_session.execute(select(ToolCall).where(ToolCall.execution_id == execution.id))).scalars().all()
    )
    assert len(rows) == 1
    assert rows[0].status == "error"


async def test_execute_tool_unknown_tool_raises(tmp_workspace: Workspace) -> None:
    registry = build_default_registry()
    context = ToolContext(workspace=tmp_workspace)
    try:
        await execute_tool(registry, "does_not_exist", {}, context)
        raise AssertionError("expected ToolNotFoundError")
    except ToolNotFoundError:
        pass


async def test_execute_tool_without_db_skips_persistence(tmp_workspace: Workspace) -> None:
    registry = build_default_registry()
    context = ToolContext(workspace=tmp_workspace, execution_id="not-a-real-execution-id")

    # No db session passed: must not attempt persistence against a fake execution_id.
    result = await execute_tool(registry, "list_directory", {"path": "."}, context)
    assert result.status == "success"
