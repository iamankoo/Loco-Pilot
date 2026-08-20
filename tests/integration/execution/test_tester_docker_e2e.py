"""Real end-to-end: Tester -> execute_terminal_command -> Docker -> pytest
-> actual exit code -> TestResult -> ToolCall persistence.

Uses the deterministic fixture project at playground/sample-project (a
minimal calculator with a passing pytest suite). No LLM is involved in
these tests — Tester's deterministic fallback path is exercised directly,
so there is nothing scripted about the test *execution* itself: pytest
genuinely runs inside a genuine container.
"""

from __future__ import annotations

import shutil
import uuid
from pathlib import Path

from sqlalchemy import select

from agents.permissions import TESTER_PERMISSIONS
from agents.state import ExecutionState
from agents.tester import TesterAgent
from backend.app.db.models.tool_call import ToolCall
from backend.app.db.repositories.executions import create_execution
from backend.app.db.repositories.projects import create_project
from backend.app.services.tool_execution import BoundToolRunner
from tools.base import ToolContext
from tools.registry import build_default_registry
from tools.workspace import Workspace

FIXTURE_ROOT = Path(__file__).resolve().parents[3] / "playground" / "sample-project"


def _copy_fixture(tmp_path: Path, name: str = "calculator") -> Workspace:
    dest = tmp_path / name
    shutil.copytree(FIXTURE_ROOT, dest)
    return Workspace.at(dest)


async def test_tester_runs_real_pytest_in_docker_against_passing_fixture(db_session, tmp_path: Path) -> None:
    workspace = _copy_fixture(tmp_path)
    project = await create_project(db_session, name=f"proj-{uuid.uuid4()}", workspace_path=str(workspace.root))
    execution = await create_execution(db_session, project_id=project.id, task="run the test suite")

    context = ToolContext(workspace=workspace, execution_id=str(execution.id))
    runner = BoundToolRunner(
        registry=build_default_registry(), context=context, permissions=TESTER_PERMISSIONS, db=db_session
    )

    agent = TesterAgent(llm_client=None, tools=runner)
    state = ExecutionState(
        execution_id=str(execution.id),
        project_id=str(project.id),
        user_task="run the test suite",
        workspace_root=str(workspace.root),
    )
    update = await agent.run(state)

    test_result = update["test_results"]
    assert test_result.status == "passed"
    assert "Command exited 0" in test_result.summary
    assert test_result.commands == ["python -m pytest"]

    rows = (
        (await db_session.execute(select(ToolCall).where(ToolCall.execution_id == execution.id))).scalars().all()
    )
    exec_calls = [r for r in rows if r.tool_name == "execute_terminal_command"]
    assert len(exec_calls) == 1
    assert exec_calls[0].status == "success"
    assert exec_calls[0].output["exit_code"] == 0
    assert "4 passed" in exec_calls[0].output["stdout"] or "passed" in exec_calls[0].output["stdout"]


async def test_tester_reports_failure_for_genuinely_broken_fixture(db_session, tmp_path: Path) -> None:
    """A copy of the fixture with a real bug introduced — pytest must
    genuinely fail, not be told to fail."""
    workspace = _copy_fixture(tmp_path, name="broken-calculator")
    (workspace.root / "calculator.py").write_text(
        "def add(a, b):\n    return a + b\n\n"
        "def subtract(a, b):\n    return a - b\n\n"
        "def multiply(a, b):\n    return a + b  # bug: should multiply\n\n"
        "def divide(a, b):\n    return a / b\n",
        encoding="utf-8",
    )

    project = await create_project(db_session, name=f"proj-{uuid.uuid4()}", workspace_path=str(workspace.root))
    execution = await create_execution(db_session, project_id=project.id, task="run the test suite")

    context = ToolContext(workspace=workspace, execution_id=str(execution.id))
    runner = BoundToolRunner(
        registry=build_default_registry(), context=context, permissions=TESTER_PERMISSIONS, db=db_session
    )

    agent = TesterAgent(llm_client=None, tools=runner)
    state = ExecutionState(
        execution_id=str(execution.id),
        project_id=str(project.id),
        user_task="run the test suite",
        workspace_root=str(workspace.root),
    )
    update = await agent.run(state)

    test_result = update["test_results"]
    assert test_result.status == "failed"
    assert "test_multiply" in test_result.errors[0] or "assert" in test_result.errors[0].lower()


async def test_secrets_in_test_output_are_scrubbed_before_persistence(db_session, tmp_path: Path) -> None:
    workspace_dir = tmp_path / "secret-project"
    workspace_dir.mkdir()
    (workspace_dir / "pyproject.toml").write_text("[project]\nname = \"x\"\nversion = \"0.1.0\"\n", encoding="utf-8")
    # Asserting False (not print()) guarantees the secret survives into the
    # tool's real stdout regardless of pytest's own output capturing, which
    # otherwise silently swallows print() from a passing test.
    (workspace_dir / "test_leaky.py").write_text(
        "def test_leaky():\n"
        "    assert False, 'leaked credential: sk-abcdefghijklmnopqrstuvwxyz123456'\n",
        encoding="utf-8",
    )
    workspace = Workspace.at(workspace_dir)

    project = await create_project(db_session, name=f"proj-{uuid.uuid4()}", workspace_path=str(workspace.root))
    execution = await create_execution(db_session, project_id=project.id, task="run the test suite")

    context = ToolContext(workspace=workspace, execution_id=str(execution.id))
    runner = BoundToolRunner(
        registry=build_default_registry(), context=context, permissions=TESTER_PERMISSIONS, db=db_session
    )

    agent = TesterAgent(llm_client=None, tools=runner)
    state = ExecutionState(
        execution_id=str(execution.id),
        project_id=str(project.id),
        user_task="run the test suite",
        workspace_root=str(workspace.root),
    )
    await agent.run(state)

    rows = (
        (await db_session.execute(select(ToolCall).where(ToolCall.execution_id == execution.id))).scalars().all()
    )
    exec_call = next(r for r in rows if r.tool_name == "execute_terminal_command")
    persisted_text = str(exec_call.output)
    assert "sk-abcdefghijklmnopqrstuvwxyz123456" not in persisted_text
    assert "REDACTED" in persisted_text
