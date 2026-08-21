"""Phase 2.5 — the autonomous coding loop, exercised through the real
graph, real filesystem, and real persistence. Four required fixtures:

A. Existing project — Developer reads the real source before editing it,
   and files_changed accurately reflects a real mutation.
B. New project — Developer creates a real directory/file structure from
   nothing, decided by the plan, not hardcoded per-task logic.
C. Multi-file change — several real tool calls tracked correctly, with
   files never touched left untouched.
D. Existing-file bug fix — a real bug fixed, producing a real diff.

Plus security tests proving Developer's LLM-driven tool-calling loop
cannot escape the workspace or reach an unauthorized tool no matter what
a (fake, scripted) "model" asks for — the permission/workspace boundary
is structural, not a matter of prompting.
"""

from __future__ import annotations

import shutil
import uuid
from pathlib import Path

import pytest

from agents.graph import GraphDependencies, build_graph
from agents.permissions import DEVELOPER_PERMISSIONS
from agents.schemas import DeveloperPlan, Plan, ReviewResult
from agents.state import ExecutionState
from backend.app.db.repositories.executions import create_execution
from backend.app.db.repositories.projects import create_project
from backend.app.services.tool_execution import BoundToolRunner
from rag.embeddings.hashing_provider import HashingEmbeddingProvider
from tests.fakes import FakeStructuredLLMClient
from tools.base import ToolContext, ToolPermissionError
from tools.registry import build_default_registry
from tools.workspace import Workspace, WorkspaceError

FIXTURE_ROOT = Path(__file__).resolve().parents[2] / "playground" / "sample-project"


def _copy_sample_project(tmp_path: Path) -> Workspace:
    dest = tmp_path / "sample-project"
    shutil.copytree(FIXTURE_ROOT, dest)
    return Workspace.at(dest)


async def _run_graph(db_session, workspace: Workspace, task: str, llm: FakeStructuredLLMClient):
    project = await create_project(db_session, name=f"proj-{uuid.uuid4()}", workspace_path=str(workspace.root))
    execution = await create_execution(db_session, project_id=project.id, task=task)
    deps = GraphDependencies(
        registry=build_default_registry(), llm_client=llm, embedding_provider=HashingEmbeddingProvider(), db=db_session
    )
    graph = build_graph(deps)
    initial_state = ExecutionState(
        execution_id=str(execution.id), project_id=str(project.id), user_task=task, workspace_root=str(workspace.root)
    )
    return await graph.ainvoke(initial_state)


# ---- Fixture A: existing project -----------------------------------------


async def test_fixture_a_existing_project_developer_reads_then_modifies_the_correct_file(
    db_session, tmp_path: Path
) -> None:
    workspace = _copy_sample_project(tmp_path)

    llm = FakeStructuredLLMClient(
        {
            "Plan": Plan(
                objective="add a factorial function",
                steps=["inspect calculator.py", "add a factorial function"],
                testing_strategy="pytest",
                files_likely_involved=["calculator.py"],
            ),
            "DeveloperPlan": DeveloperPlan(summary="added a factorial function"),
            "ReviewResult": ReviewResult(verdict="approved", summary="looks correct"),
        },
        tool_call_scripts=[
            [
                ("read_file", {"path": "calculator.py"}),
                (
                    "edit_file",
                    {
                        "path": "calculator.py",
                        "old_string": "def divide(a, b):\n    return a / b\n",
                        "new_string": (
                            "def divide(a, b):\n    return a / b\n\n\n"
                            "def factorial(n):\n    return 1 if n <= 1 else n * factorial(n - 1)\n"
                        ),
                    },
                ),
            ]
        ],
    )

    final = await _run_graph(db_session, workspace, "Add a function to calculate factorial", llm)

    content = (workspace.root / "calculator.py").read_text()
    assert "def factorial(n):" in content
    assert "def add(a, b):" in content  # unrelated code preserved

    assert len(final["files_changed"]) == 1
    assert final["files_changed"][0].path == "calculator.py"
    assert final["files_changed"][0].change_type == "modified"


# ---- Fixture B: new project -----------------------------------------------


async def test_fixture_b_new_project_developer_creates_directory_structure_and_files(
    db_session, tmp_path: Path
) -> None:
    workspace = Workspace.at(tmp_path)  # an empty, freshly-provisioned workspace — nothing exists yet

    llm = FakeStructuredLLMClient(
        {
            "Plan": Plan(
                objective="create a C++ calculator project",
                steps=["scaffold the project structure", "implement a basic calculator", "add a CMake build file"],
                testing_strategy="CTest",
            ),
            "DeveloperPlan": DeveloperPlan(summary="scaffolded a new C++ calculator project"),
            "ReviewResult": ReviewResult(verdict="approved", summary="structure looks reasonable"),
        },
        tool_call_scripts=[
            [
                ("write_file", {"path": "CMakeLists.txt", "content": "cmake_minimum_required(VERSION 3.10)\nproject(calculator)\nadd_executable(calculator src/main.cpp)\n"}),
                ("write_file", {"path": "src/main.cpp", "content": "#include <iostream>\nint main() {\n    std::cout << 1 + 1 << std::endl;\n    return 0;\n}\n"}),
                ("write_file", {"path": "README.md", "content": "# C++ Calculator\n"}),
            ]
        ],
    )

    final = await _run_graph(db_session, workspace, "Create a C++ calculator", llm)

    assert (workspace.root / "CMakeLists.txt").is_file()
    assert (workspace.root / "src" / "main.cpp").is_file()
    assert (workspace.root / "README.md").is_file()
    assert "add_executable" in (workspace.root / "CMakeLists.txt").read_text()

    change_types = {f.path: f.change_type for f in final["files_changed"]}
    assert change_types["CMakeLists.txt"] == "created"
    assert change_types["src/main.cpp"] == "created"
    assert change_types["README.md"] == "created"


# ---- Fixture C: multi-file change -----------------------------------------


async def test_fixture_c_multi_file_change_tracks_every_mutation_and_leaves_others_untouched(
    db_session, tmp_path: Path
) -> None:
    workspace = _copy_sample_project(tmp_path)
    (workspace.root / "constants.py").write_text("PI = 3.14\n", encoding="utf-8")
    original_constants = (workspace.root / "constants.py").read_text()

    llm = FakeStructuredLLMClient(
        {
            "Plan": Plan(
                objective="add power and modulo operations",
                steps=["add power()", "add modulo()", "add a docstring to the module"],
                testing_strategy="pytest",
                files_likely_involved=["calculator.py"],
            ),
            "DeveloperPlan": DeveloperPlan(summary="added power/modulo and a module docstring"),
            "ReviewResult": ReviewResult(verdict="approved", summary="looks correct"),
        },
        tool_call_scripts=[
            [
                ("read_file", {"path": "calculator.py"}),
                (
                    "edit_file",
                    {
                        "path": "calculator.py",
                        "old_string": "def divide(a, b):\n    return a / b\n",
                        "new_string": "def divide(a, b):\n    return a / b\n\n\ndef power(a, b):\n    return a ** b\n",
                    },
                ),
                ("write_file", {"path": "modulo.py", "content": "def modulo(a, b):\n    return a % b\n"}),
            ]
        ],
    )

    final = await _run_graph(db_session, workspace, "Add power and modulo operations", llm)

    assert "def power(a, b):" in (workspace.root / "calculator.py").read_text()
    assert (workspace.root / "modulo.py").is_file()
    # A file that had nothing to do with this task was never touched.
    assert (workspace.root / "constants.py").read_text() == original_constants

    changed_paths = {f.path for f in final["files_changed"]}
    assert changed_paths == {"calculator.py", "modulo.py"}
    assert "constants.py" not in changed_paths


# ---- Fixture D: existing-file bug fix with a real diff --------------------


async def test_fixture_d_existing_file_bug_fix_produces_a_real_diff(db_session, tmp_path: Path) -> None:
    workspace = _copy_sample_project(tmp_path)
    (workspace.root / "calculator.py").write_text(
        "def add(a, b):\n    return a + b\n\n\ndef subtract(a, b):\n    return a + b  # BUG: should subtract\n",
        encoding="utf-8",
    )

    llm = FakeStructuredLLMClient(
        {
            "Plan": Plan(
                objective="fix the subtract bug",
                steps=["inspect calculator.py", "fix subtract()"],
                testing_strategy="pytest",
                files_likely_involved=["calculator.py"],
            ),
            "DeveloperPlan": DeveloperPlan(summary="fixed subtract to actually subtract"),
            "ReviewResult": ReviewResult(verdict="approved", summary="fix looks correct"),
        },
        tool_call_scripts=[
            [
                ("read_file", {"path": "calculator.py"}),
                (
                    "edit_file",
                    {
                        "path": "calculator.py",
                        "old_string": "    return a + b  # BUG: should subtract",
                        "new_string": "    return a - b",
                    },
                ),
            ]
        ],
    )

    final = await _run_graph(db_session, workspace, "Fix the subtract bug in calculator.py", llm)

    assert "return a - b" in (workspace.root / "calculator.py").read_text()
    assert "BUG" not in (workspace.root / "calculator.py").read_text()

    edit_calls = [tc for tc in final["tool_calls"] if tc.tool_name == "edit_file"]
    assert len(edit_calls) == 1
    assert edit_calls[0].status == "success"
    assert final["files_changed"][0].change_type == "modified"


# ---- Security: Developer's tool-calling loop cannot escape ----------------


async def test_developer_tool_call_escaping_workspace_is_rejected_not_executed(tmp_path: Path) -> None:
    """Even if a (fake, scripted) "model" asks to write outside the
    workspace, the real tool layer rejects it structurally — the
    permission/workspace boundary does not depend on the model behaving."""
    workspace = Workspace.at(tmp_path)
    context = ToolContext(workspace=workspace)
    runner = BoundToolRunner(registry=build_default_registry(), context=context, permissions=DEVELOPER_PERMISSIONS)

    result = await runner.call("write_file", {"path": "../../escape.txt", "content": "malicious"})
    assert result.status == "error"
    assert not (tmp_path.parent.parent / "escape.txt").exists()


async def test_developer_cannot_reach_an_unauthorized_tool_via_bound_tool_runner(tmp_path: Path) -> None:
    workspace = Workspace.at(tmp_path)
    context = ToolContext(workspace=workspace)
    runner = BoundToolRunner(registry=build_default_registry(), context=context, permissions=DEVELOPER_PERMISSIONS)

    with pytest.raises(ToolPermissionError):
        await runner.call("execute_terminal_command", {"command": ["echo", "hi"]})


async def test_developer_agent_run_never_touches_the_host_filesystem_outside_workspace(tmp_path: Path) -> None:
    """End-to-end through the actual DeveloperAgent (not just the tool
    layer directly): a scripted attempt to write outside the workspace via
    a relative traversal path must fail loudly (a ToolError bubbles up as
    a `change_type="failed"` FileChange), never silently succeed outside
    the workspace boundary."""
    from agents.developer import DeveloperAgent
    from tests.fakes import FakeToolRunner
    from tools.execution_result import ToolExecutionResult

    plan = Plan(objective="x", steps=["a"], testing_strategy="t")
    llm = FakeStructuredLLMClient(
        {"DeveloperPlan": DeveloperPlan(summary="done")},
        tool_call_scripts=[[("write_file", {"path": "../outside.txt", "content": "malicious"})]],
    )

    real_workspace = Workspace.at(tmp_path)

    class _RealBoundaryToolRunner(FakeToolRunner):
        async def call(self, tool_name: str, tool_input: dict) -> ToolExecutionResult:
            if tool_name == "write_file":
                try:
                    real_workspace.resolve(tool_input["path"])
                except WorkspaceError as exc:
                    return ToolExecutionResult(tool_name=tool_name, status="error", output=None, error=str(exc), duration_ms=0)
            return await super().call(tool_name, tool_input)

    tools = _RealBoundaryToolRunner(allowed={"read_file", "write_file", "edit_file"})
    state = ExecutionState(
        execution_id="11111111-1111-1111-1111-111111111111",
        project_id="22222222-2222-2222-2222-222222222222",
        user_task="x",
        workspace_root=str(tmp_path),
        plan=plan,
    )

    agent = DeveloperAgent(llm_client=llm, tools=tools)
    update = await agent.run(state)

    assert update["files_changed"][0].change_type == "failed"
    assert not (tmp_path.parent / "outside.txt").exists()
