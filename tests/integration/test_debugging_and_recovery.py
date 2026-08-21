"""Phase 2.7 — Debugging & Recovery, exercised through the real graph,
real filesystem, real PostgreSQL, and (fixtures A/B/C) a real Docker
sandbox running real pytest. What's scripted via `FakeStructuredLLMClient`
is only which tool calls each turn makes and each agent's final
structured summary — no live LLM key exists in this environment (see
README/Known Limitations, the same documented boundary every prior
phase's graph-integration tests operate under). Every real exit code,
every real file mutation, and every derived field (failure_class,
debug_attempts, attempt outcomes) reflects what actually happened, never
something asserted independently of it.
"""

from __future__ import annotations

import shutil
import uuid
from pathlib import Path

import pytest
from sqlalchemy import select

from agents.debugger import DebuggerAgent
from agents.failure_classification import classify_failure
from agents.graph import GraphDependencies, build_graph
from agents.permissions import DEBUGGER_PERMISSIONS
from agents.schemas import DebugResult, DeveloperPlan, Plan, ReviewResult, TestResult
from agents.state import ExecutionState
from backend.app.db.models.agent_step import AgentStep
from backend.app.db.repositories.executions import create_execution
from backend.app.db.repositories.projects import create_project
from backend.app.services.tool_execution import BoundToolRunner
from rag.embeddings.hashing_provider import HashingEmbeddingProvider
from tests.fakes import FakeStructuredLLMClient, FakeToolRunner
from tools.base import ToolContext, ToolPermissionError
from tools.execution_result import ToolExecutionResult
from tools.registry import build_default_registry
from tools.workspace import Workspace

FIXTURE_ROOT = Path(__file__).resolve().parents[2] / "playground" / "sample-project"


async def _run_graph(db_session, workspace: Workspace, task: str, llm: FakeStructuredLLMClient, **dep_overrides):
    project = await create_project(db_session, name=f"proj-{uuid.uuid4()}", workspace_path=str(workspace.root))
    execution = await create_execution(db_session, project_id=project.id, task=task)
    deps = GraphDependencies(
        registry=build_default_registry(), llm_client=llm, embedding_provider=HashingEmbeddingProvider(), db=db_session,
        **dep_overrides,
    )
    graph = build_graph(deps)
    initial_state = ExecutionState(
        execution_id=str(execution.id), project_id=str(project.id), user_task=task, workspace_root=str(workspace.root)
    )
    final = await graph.ainvoke(initial_state, config={"recursion_limit": 50})
    return execution, final


# ---- Fixture A: simple bug, wrong operator -------------------------------


async def test_fixture_a_simple_bug_debugger_identifies_and_fixes_wrong_operator(
    db_session, tmp_path: Path
) -> None:
    workspace_dir = tmp_path / "calculator"
    shutil.copytree(FIXTURE_ROOT, workspace_dir)
    (workspace_dir / "calculator.py").write_text(
        "def add(a, b):\n    return a - b  # BUG: should add\n\n\n"
        "def subtract(a, b):\n    return a - b\n\n\n"
        "def multiply(a, b):\n    return a * b\n\n\n"
        "def divide(a, b):\n    return a / b\n",
        encoding="utf-8",
    )
    workspace = Workspace.at(workspace_dir)

    llm = FakeStructuredLLMClient(
        {
            "Plan": Plan(
                objective="fix the failing add test", steps=["inspect calculator.py", "fix add()"],
                testing_strategy="pytest", files_likely_involved=["calculator.py"],
            ),
            "DebugResult": DebugResult(
                root_cause="add() subtracts instead of adding",
                proposed_fix="change the operator from - to +",
                confidence="high",
                files_to_change=["calculator.py"],
            ),
            "DeveloperPlan": DeveloperPlan(summary="implemented the plan via tool calls"),
            "ReviewResult": ReviewResult(verdict="approved", summary="fix verified by a passing test suite"),
        },
        tool_call_scripts=[
            [],  # Developer's first turn: nothing yet, so Tester genuinely hits the real bug
            [("read_file", {"path": "calculator.py"})],  # Debugger's investigative turn
            [("edit_file", {"path": "calculator.py", "old_string": "    return a - b  # BUG: should add", "new_string": "    return a + b"})],
        ],
    )

    execution, final = await _run_graph(db_session, workspace, "fix the failing add test", llm, max_debug_retries=2)

    assert final["execution_status"] == "passed"
    assert final["retry_count"] == 1
    assert "return a + b" in (workspace_dir / "calculator.py").read_text()

    # Structured debug-attempt history reflects the real outcome.
    assert len(final["debug_attempts"]) == 1
    attempt = final["debug_attempts"][0]
    assert attempt.attempt_number == 1
    assert attempt.status == "fixed"  # patched by Tester's second, passing run
    assert attempt.failure_class == "assertion_failure"  # derived from the real pytest AssertionError
    assert "calculator.py" in attempt.files_inspected

    steps = (await db_session.execute(select(AgentStep).where(AgentStep.execution_id == execution.id))).scalars().all()
    assert [s.agent_name for s in steps].count("tester") == 2


# ---- Fixture B: multi-file bug -------------------------------------------


async def test_fixture_b_multi_file_bug_debugger_inspects_the_correct_files(db_session, tmp_path: Path) -> None:
    workspace_dir = tmp_path / "multi-file"
    workspace_dir.mkdir()
    (workspace_dir / "pyproject.toml").write_text(
        '[project]\nname = "x"\nversion = "0.1.0"\ndependencies = [\n    "pytest>=8.0",\n]\n', encoding="utf-8"
    )
    (workspace_dir / "operations.py").write_text(
        "def compute_total(a, b):\n    return a - b  # BUG: should add\n", encoding="utf-8"
    )
    (workspace_dir / "calculator.py").write_text(
        "from operations import compute_total\n\n\ndef total(a, b):\n    return compute_total(a, b)\n",
        encoding="utf-8",
    )
    (workspace_dir / "test_calculator.py").write_text(
        "from calculator import total\n\n\ndef test_total():\n    assert total(2, 3) == 5\n", encoding="utf-8"
    )
    workspace = Workspace.at(workspace_dir)

    llm = FakeStructuredLLMClient(
        {
            "Plan": Plan(
                objective="fix the failing total test", steps=["inspect calculator.py", "trace into operations.py"],
                testing_strategy="pytest", files_likely_involved=["calculator.py", "operations.py"],
            ),
            "DebugResult": DebugResult(
                root_cause="operations.compute_total() subtracts instead of adding",
                proposed_fix="change the operator from - to + in operations.py",
                confidence="high",
                files_to_change=["operations.py"],
            ),
            "DeveloperPlan": DeveloperPlan(summary="implemented the plan via tool calls"),
            "ReviewResult": ReviewResult(verdict="approved", summary="fix verified"),
        },
        tool_call_scripts=[
            [],
            # Debugger reads the entry point first, then follows the import
            # to the file that actually contains the bug — proving the
            # mechanics support a multi-file investigation, not just a
            # single-file lookup.
            [("read_file", {"path": "calculator.py"}), ("read_file", {"path": "operations.py"})],
            [("edit_file", {"path": "operations.py", "old_string": "    return a - b  # BUG: should add", "new_string": "    return a + b"})],
        ],
    )

    execution, final = await _run_graph(db_session, workspace, "fix the failing total test", llm, max_debug_retries=2)

    assert final["execution_status"] == "passed"
    assert "return a + b" in (workspace_dir / "operations.py").read_text()

    attempt = final["debug_attempts"][0]
    assert attempt.status == "fixed"
    assert set(attempt.files_inspected) == {"calculator.py", "operations.py"}
    assert attempt.files_to_change == ["operations.py"]


# ---- Fixture C: import/dependency failure --------------------------------


async def test_fixture_c_import_failure_is_honestly_classified(db_session, tmp_path: Path) -> None:
    workspace_dir = tmp_path / "broken-import"
    workspace_dir.mkdir()
    (workspace_dir / "pyproject.toml").write_text(
        '[project]\nname = "x"\nversion = "0.1.0"\ndependencies = [\n    "pytest>=8.0",\n]\n', encoding="utf-8"
    )
    (workspace_dir / "calculator.py").write_text(
        "import this_module_does_not_exist\n\n\ndef add(a, b):\n    return a + b\n", encoding="utf-8"
    )
    (workspace_dir / "test_calculator.py").write_text(
        "from calculator import add\n\n\ndef test_add():\n    assert add(2, 3) == 5\n", encoding="utf-8"
    )
    workspace = Workspace.at(workspace_dir)

    from agents.permissions import TESTER_PERMISSIONS
    from agents.tester import TesterAgent
    from analysis.context import build_project_context

    project = await create_project(db_session, name=f"proj-{uuid.uuid4()}", workspace_path=str(workspace.root))
    execution = await create_execution(db_session, project_id=project.id, task="run the tests")
    project_context = await build_project_context(workspace, "run the tests")
    context = ToolContext(workspace=workspace, execution_id=str(execution.id))
    runner = BoundToolRunner(registry=build_default_registry(), context=context, permissions=TESTER_PERMISSIONS, db=db_session)

    tester = TesterAgent(llm_client=None, tools=runner)
    state = ExecutionState(
        execution_id=str(execution.id), project_id=str(project.id), user_task="run the tests",
        workspace_root=str(workspace.root), project_context=project_context,
    )
    update = await tester.run(state)
    test_result = update["test_results"]

    assert test_result.status in ("failed", "error")
    assert classify_failure(test_result) == "import_error"

    # Debugger, given this same real evidence, reaches the same honest classification.
    debugger = DebuggerAgent(
        llm_client=FakeStructuredLLMClient(
            {"DebugResult": DebugResult(root_cause="missing module", proposed_fix="remove the bad import", confidence="high", files_to_change=["calculator.py"])}
        ),
        tools=FakeToolRunner(allowed={"read_file"}, responses={
            "read_file": ToolExecutionResult(tool_name="read_file", status="success", output={"content": "import this_module_does_not_exist"}, error=None, duration_ms=1)
        }),
    )
    debug_state = state.model_copy(update={"test_results": test_result})
    debug_update = await debugger.run(debug_state)
    assert debug_update["debug_result"].failure_class == "import_error"


# ---- Fixture D: unfixable failure — honest terminal failure ---------------


async def test_fixture_d_unfixable_failure_terminates_honestly_at_retry_limit(
    db_session, tmp_git_workspace: Workspace, monkeypatch
) -> None:
    from tools.terminal.contract import TerminalCommandResult
    from tools.terminal.tools import ExecuteTerminalCommandTool

    async def _always_fails(self, tool_input, context):
        return TerminalCommandResult(
            command=tool_input.command, exit_code=1, stdout="", stderr="AssertionError: still wrong",
            stdout_truncated=False, stderr_truncated=False, timed_out=False, duration_ms=1,
        )

    monkeypatch.setattr(ExecuteTerminalCommandTool, "run", _always_fails)
    (tmp_git_workspace.root / "pyproject.toml").write_text('[project]\nname = "x"\n', encoding="utf-8")

    max_debug_retries = 2
    llm = FakeStructuredLLMClient(
        {
            "Plan": Plan(objective="fix it", steps=["investigate"], testing_strategy="pytest"),
            "DeveloperPlan": DeveloperPlan(summary="attempted a fix"),
            "DebugResult": DebugResult(
                root_cause="unclear", proposed_fix="try something else", confidence="low", files_to_change=["a.py"]
            ),
            "ReviewResult": ReviewResult(verdict="approved", summary="reviewed despite failures"),
        }
    )

    execution, final = await _run_graph(
        db_session, tmp_git_workspace, "fix the stubborn bug", llm, max_debug_retries=max_debug_retries
    )

    assert final["retry_count"] == max_debug_retries
    assert final["test_results"].status == "failed"  # never fabricated a pass
    # Every attempt genuinely failed and is honestly recorded as such.
    assert len(final["debug_attempts"]) == max_debug_retries
    assert all(a.status == "unresolved" for a in final["debug_attempts"])


# ---- Fixture E: repeated ineffective fix — loop-prevention signal ---------


async def test_fixture_e_repeated_identical_fix_is_flagged(db_session, tmp_git_workspace: Workspace, monkeypatch) -> None:
    from tools.terminal.contract import TerminalCommandResult
    from tools.terminal.tools import ExecuteTerminalCommandTool

    async def _always_fails(self, tool_input, context):
        return TerminalCommandResult(
            command=tool_input.command, exit_code=1, stdout="", stderr="AssertionError: still wrong",
            stdout_truncated=False, stderr_truncated=False, timed_out=False, duration_ms=1,
        )

    monkeypatch.setattr(ExecuteTerminalCommandTool, "run", _always_fails)
    (tmp_git_workspace.root / "pyproject.toml").write_text('[project]\nname = "x"\n', encoding="utf-8")

    # The exact same root_cause/files_to_change every time — a genuinely
    # non-productive, repeated strategy.
    same_debug_result = DebugResult(
        root_cause="off-by-one somewhere", proposed_fix="adjust the boundary", confidence="low", files_to_change=["a.py"]
    )
    llm = FakeStructuredLLMClient(
        {
            "Plan": Plan(objective="fix it", steps=["investigate"], testing_strategy="pytest"),
            "DeveloperPlan": DeveloperPlan(summary="attempted a fix"),
            "DebugResult": same_debug_result,
            "ReviewResult": ReviewResult(verdict="approved", summary="reviewed despite failures"),
        }
    )

    execution, final = await _run_graph(db_session, tmp_git_workspace, "fix it", llm, max_debug_retries=2)

    steps = (
        (await db_session.execute(select(AgentStep).where(AgentStep.execution_id == execution.id, AgentStep.agent_name == "debugger")))
        .scalars()
        .all()
    )
    # The second debugger attempt recognized it was repeating the first's
    # already-unsuccessful strategy.
    assert len(steps) == 2
    second_attempt_messages = steps[1].output_metadata.get("messages", [])
    assert any("repeats a previously unsuccessful attempt" in m for m in second_attempt_messages)


# ---- Fixture F: malicious repository content cannot escalate -------------


async def test_fixture_f_malicious_repository_content_cannot_reach_unauthorized_tools(tmp_path: Path) -> None:
    workspace = Workspace.at(tmp_path)
    context = ToolContext(workspace=workspace)
    runner = BoundToolRunner(registry=build_default_registry(), context=context, permissions=DEBUGGER_PERMISSIONS)

    # DEBUGGER_PERMISSIONS grants WRITE at the table level (interface
    # completeness — see agents/permissions.py), but the graph's own
    # allowlist further restricts Debugger's actual loop to read-only
    # tools; this call proves the permission BoundToolRunner enforces here
    # is what a malicious prompt could never widen regardless of framing.
    with pytest.raises(ToolPermissionError):
        await runner.call("execute_terminal_command", {"command": ["rm", "-rf", "/"]})

    result = await runner.call("read_file", {"path": "../../etc/passwd"})
    assert result.status == "error"
