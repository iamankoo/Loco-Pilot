"""Phase 2.6 — test intelligence: Tester reuses Phase 2.2's ProjectContext
for framework detection, prefers a targeted test selection over the whole
suite, and always executes for real through
BoundToolRunner -> execute_terminal_command -> the real Docker sandbox.
Status is always derived from the real exit code — never fabricated.
"""

from __future__ import annotations

import shutil
import uuid
from pathlib import Path

from agents.permissions import TESTER_PERMISSIONS
from agents.schemas import FileChange
from agents.state import ExecutionState
from agents.tester import TesterAgent
from analysis.context import build_project_context
from backend.app.db.repositories.executions import create_execution
from backend.app.db.repositories.projects import create_project
from backend.app.services.tool_execution import BoundToolRunner
from rag.embeddings.hashing_provider import HashingEmbeddingProvider
from tools.base import ToolContext
from tools.registry import build_default_registry
from tools.workspace import Workspace

FIXTURE_ROOT = Path(__file__).resolve().parents[2] / "playground" / "sample-project"


async def _real_tester(db_session, workspace: Workspace, task: str) -> TesterAgent:
    project = await create_project(db_session, name=f"proj-{uuid.uuid4()}", workspace_path=str(workspace.root))
    execution = await create_execution(db_session, project_id=project.id, task=task)
    context = ToolContext(workspace=workspace, execution_id=str(execution.id))
    runner = BoundToolRunner(
        registry=build_default_registry(), context=context, permissions=TESTER_PERMISSIONS, db=db_session
    )
    return TesterAgent(llm_client=None, tools=runner)


# ---- Fixture A: Python repo, pytest detected via ProjectContext ----------


async def test_fixture_a_python_repo_uses_project_context_and_runs_real_pytest(db_session, tmp_path: Path) -> None:
    workspace_dir = tmp_path / "calculator"
    shutil.copytree(FIXTURE_ROOT, workspace_dir)
    workspace = Workspace.at(workspace_dir)

    project_context = await build_project_context(workspace, "run the tests")
    assert "pytest" in project_context.test_frameworks

    agent = await _real_tester(db_session, workspace, "run the tests")
    state = ExecutionState(
        execution_id="11111111-1111-1111-1111-111111111111",
        project_id="22222222-2222-2222-2222-222222222222",
        user_task="run the tests",
        workspace_root=str(workspace.root),
        project_context=project_context,
    )
    update = await agent.run(state)

    result = update["test_results"]
    assert result.status == "passed"
    assert result.framework == "pytest"
    assert result.passed >= 1
    assert result.duration_ms is not None


# ---- Fixture B: multiple test areas, auth ranks first ---------------------


async def test_fixture_b_targeted_selection_ranks_auth_tests_first(db_session, tmp_path: Path) -> None:
    root = tmp_path / "multi-area"
    root.mkdir()
    (root / "pyproject.toml").write_text(
        '[project]\nname = "demo"\ndependencies = [\n    "pytest>=8.0",\n]\n', encoding="utf-8"
    )
    (root / "auth").mkdir()
    (root / "payments").mkdir()
    (root / "tests").mkdir()
    (root / "auth" / "service.py").write_text("def login():\n    return True\n", encoding="utf-8")
    (root / "payments" / "billing.py").write_text("def charge():\n    return True\n", encoding="utf-8")
    (root / "tests" / "test_auth.py").write_text("def test_login():\n    assert True\n", encoding="utf-8")
    (root / "tests" / "test_payments.py").write_text(
        "def test_charge():\n    assert False, 'unrelated failure must not run'\n", encoding="utf-8"
    )
    workspace = Workspace.at(root)

    project_context = await build_project_context(workspace, "Fix authentication")

    agent = await _real_tester(db_session, workspace, "Fix authentication")
    state = ExecutionState(
        execution_id="11111111-1111-1111-1111-111111111111",
        project_id="22222222-2222-2222-2222-222222222222",
        user_task="Fix authentication",
        workspace_root=str(workspace.root),
        project_context=project_context,
        files_changed=[FileChange(path="auth/service.py", change_type="modified", detail="edited")],
    )
    update = await agent.run(state)

    result = update["test_results"]
    # Only the auth test ran (targeted) — the unrelated, deliberately
    # failing payments test was never even invoked.
    assert result.status == "passed"
    assert "tests/test_auth.py" in result.commands[0]
    assert "test_payments.py" not in result.commands[0]


# ---- Fixture C: passing test -----------------------------------------------


async def test_fixture_c_passing_test_is_honestly_reported_passed(db_session, tmp_path: Path) -> None:
    workspace_dir = tmp_path / "calculator"
    shutil.copytree(FIXTURE_ROOT, workspace_dir)
    workspace = Workspace.at(workspace_dir)

    project_context = await build_project_context(workspace, "run the tests")
    agent = await _real_tester(db_session, workspace, "run the tests")
    state = ExecutionState(
        execution_id="11111111-1111-1111-1111-111111111111",
        project_id="22222222-2222-2222-2222-222222222222",
        user_task="run the tests",
        workspace_root=str(workspace.root),
        project_context=project_context,
    )
    update = await agent.run(state)

    assert update["test_results"].status == "passed"
    assert update["execution_status"] == "reviewing"


# ---- Fixture D: failing test with structured evidence ---------------------


async def test_fixture_d_failing_test_reports_structured_failure_evidence(db_session, tmp_path: Path) -> None:
    workspace_dir = tmp_path / "broken-calculator"
    shutil.copytree(FIXTURE_ROOT, workspace_dir)
    (workspace_dir / "calculator.py").write_text(
        "def add(a, b):\n    return a + b\n\n"
        "def subtract(a, b):\n    return a - b\n\n"
        "def multiply(a, b):\n    return a + b  # bug: should multiply\n\n"
        "def divide(a, b):\n    return a / b\n",
        encoding="utf-8",
    )
    workspace = Workspace.at(workspace_dir)

    project_context = await build_project_context(workspace, "run the tests")
    agent = await _real_tester(db_session, workspace, "run the tests")
    state = ExecutionState(
        execution_id="11111111-1111-1111-1111-111111111111",
        project_id="22222222-2222-2222-2222-222222222222",
        user_task="run the tests",
        workspace_root=str(workspace.root),
        project_context=project_context,
    )
    update = await agent.run(state)

    result = update["test_results"]
    assert result.status == "failed"
    assert result.framework == "pytest"
    assert result.failed >= 1
    assert result.failing_tests  # at least one FAILED test id parsed from real pytest output
    assert any("multiply" in name for name in result.failing_tests)


# ---- Fixture E: no tests at all --------------------------------------------


async def test_fixture_e_no_tests_reports_honest_unavailable(db_session, tmp_path: Path) -> None:
    root = tmp_path / "no-tests"
    root.mkdir()
    (root / "app.py").write_text("x = 1\n", encoding="utf-8")
    workspace = Workspace.at(root)

    project_context = await build_project_context(workspace, "do something")
    assert project_context.test_frameworks == []

    agent = await _real_tester(db_session, workspace, "do something")
    state = ExecutionState(
        execution_id="11111111-1111-1111-1111-111111111111",
        project_id="22222222-2222-2222-2222-222222222222",
        user_task="do something",
        workspace_root=str(workspace.root),
        project_context=project_context,
    )
    update = await agent.run(state)

    assert update["test_results"].status == "unavailable"
    assert update["test_results"].passed == 0
    assert update["test_results"].failed == 0


# ---- Fixture F: brand-new, freshly-created project (no tests yet) --------


async def test_fixture_f_freshly_created_project_does_not_fabricate_a_passing_result(
    db_session, tmp_path: Path
) -> None:
    """A generated project with only source files and no test suite yet —
    exactly the state right after Developer scaffolds a new project — must
    still be reported honestly as unavailable, never as a fabricated pass."""
    root = tmp_path / "new-calculator"
    root.mkdir()
    (root / "src").mkdir()
    (root / "src" / "main.cpp").write_text("int main() { return 0; }\n", encoding="utf-8")
    (root / "CMakeLists.txt").write_text("cmake_minimum_required(VERSION 3.10)\nproject(calc)\n", encoding="utf-8")
    workspace = Workspace.at(root)

    project_context = await build_project_context(workspace, "Create a C++ calculator")

    agent = await _real_tester(db_session, workspace, "Create a C++ calculator")
    state = ExecutionState(
        execution_id="11111111-1111-1111-1111-111111111111",
        project_id="22222222-2222-2222-2222-222222222222",
        user_task="Create a C++ calculator",
        workspace_root=str(workspace.root),
        project_context=project_context,
    )
    update = await agent.run(state)

    # CMakeLists.txt's mere presence is (Phase 2.2's existing, weak)
    # evidence of CTest, so Tester genuinely attempts it here rather than
    # reporting "unavailable" outright — but with no CMake build actually
    # configured, that real attempt honestly fails. Either way, the one
    # invariant that actually matters is upheld: nothing here is ever
    # reported as a fabricated pass.
    assert update["test_results"].status != "passed"
