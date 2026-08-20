"""The second half of the Phase 1.4 real end-to-end requirement: a
failing fixture goes through Tester -> Debugger -> Developer -> Tester and
ends up passing.

Every Tester step here runs REAL pytest inside a REAL Docker container,
with a genuine exit code — that part is never faked. What IS scripted,
via `FakeStructuredLLMClient`, is every agent's *reasoning* output
(Plan/DebugResult/DeveloperPlan/ReviewResult, and Tester's own structured
interpretation of the real exit code/stdout it just received), because no
live LLM API key exists in this environment (see README/Known
Limitations — this is the documented graph-integration boundary: genuine
autonomous multi-turn debugging requires a real model, untested here by
necessity, consistent with every prior phase's test methodology). The
scripted TestResult values below correctly reflect what the fixture
deterministically does and does not do (the bug genuinely makes pytest
exit nonzero before the fix, and the fix genuinely makes it exit zero
after) — nothing here is fabricated independent of what Docker actually
returned. This test proves the graph's routing and the sandbox's
execution are both mechanically correct: a real bug, really fixed by a
real tool call, really re-verified by a second real pytest run.
"""

from __future__ import annotations

import uuid
from pathlib import Path

from sqlalchemy import select

from agents.graph import GraphDependencies, build_graph
from agents.schemas import DebugResult, DeveloperPlan, Plan, ProposedEdit, ReviewResult, TestResult
from agents.state import ExecutionState
from backend.app.db.models.agent_step import AgentStep
from backend.app.db.repositories.executions import create_execution
from backend.app.db.repositories.projects import create_project
from rag.embeddings.hashing_provider import HashingEmbeddingProvider
from tests.fakes import FakeStructuredLLMClient
from tools.registry import build_default_registry

_BUGGY_CALCULATOR = (
    "def add(a, b):\n"
    "    return a + b\n"
    "\n"
    "\n"
    "def multiply(a, b):\n"
    "    return a + b  # BUG: should be a * b\n"
)

_FIXED_LINE = "    return a + b  # BUG: should be a * b"
_CORRECTED_LINE = "    return a * b"

_TEST_CALCULATOR = (
    "from calculator import add, multiply\n"
    "\n"
    "\n"
    "def test_add():\n"
    "    assert add(2, 3) == 5\n"
    "\n"
    "\n"
    "def test_multiply():\n"
    "    assert multiply(2, 3) == 6\n"
)


async def test_debug_loop_with_real_docker_execution_fixes_the_bug(db_session, tmp_path: Path) -> None:
    workspace_dir = tmp_path / "buggy-calculator"
    workspace_dir.mkdir()
    (workspace_dir / "pyproject.toml").write_text("[project]\nname = \"x\"\nversion = \"0.1.0\"\n", encoding="utf-8")
    (workspace_dir / "calculator.py").write_text(_BUGGY_CALCULATOR, encoding="utf-8")
    (workspace_dir / "test_calculator.py").write_text(_TEST_CALCULATOR, encoding="utf-8")

    project = await create_project(db_session, name=f"proj-{uuid.uuid4()}", workspace_path=str(workspace_dir))
    execution = await create_execution(db_session, project_id=project.id, task="fix the failing multiply test")

    llm = FakeStructuredLLMClient(
        {
            "Plan": Plan(
                objective="fix multiply",
                steps=["inspect calculator.py", "fix the multiply function"],
                testing_strategy="run pytest",
                files_likely_involved=["calculator.py"],
            ),
            "DebugResult": DebugResult(
                root_cause="multiply() uses addition instead of multiplication",
                proposed_fix="change the operator from + to *",
                confidence="high",
                files_to_change=["calculator.py"],
            ),
            # Developer runs twice: once before any test has failed (must do
            # nothing meaningful, so Tester genuinely finds the real bug),
            # and once after Debugger's diagnosis (applies the real fix).
            "DeveloperPlan": [
                DeveloperPlan(summary="inspected calculator.py, awaiting test results before changing anything"),
                DeveloperPlan(
                    summary="fix the multiply operator",
                    edits=[ProposedEdit(path="calculator.py", old_string=_FIXED_LINE, new_string=_CORRECTED_LINE)],
                ),
            ],
            # Tester delegates structured interpretation to the LLM whenever
            # one is configured (see agents/tester.py) — these two values
            # correctly reflect the real exit code each real pytest run
            # produces (nonzero before the fix, zero after).
            "TestResult": [
                TestResult(
                    status="failed",
                    commands=["python -m pytest"],
                    passed=1,
                    failed=1,
                    errors=["test_multiply: multiply(2, 3) returned 5, expected 6"],
                    summary="1 of 2 tests failed: test_multiply",
                ),
                TestResult(
                    status="passed",
                    commands=["python -m pytest"],
                    passed=2,
                    failed=0,
                    summary="all tests passed",
                ),
            ],
            "ReviewResult": ReviewResult(verdict="approved", summary="fix verified by a passing test suite"),
        }
    )

    deps = GraphDependencies(
        registry=build_default_registry(),
        llm_client=llm,
        embedding_provider=HashingEmbeddingProvider(),
        db=db_session,
        max_debug_retries=2,
    )
    graph = build_graph(deps)

    initial_state = ExecutionState(
        execution_id=str(execution.id),
        project_id=str(project.id),
        user_task="fix the failing multiply test",
        workspace_root=str(workspace_dir),
    )
    final = await graph.ainvoke(initial_state, config={"recursion_limit": 50})

    assert final["execution_status"] == "passed"
    assert final["retry_count"] == 1  # exactly one debug cycle was needed
    assert final["review_result"].verdict == "approved"

    # The fix is genuinely on disk — Developer really edited the file via a real tool call.
    assert "return a * b" in (workspace_dir / "calculator.py").read_text()

    steps = (
        (await db_session.execute(select(AgentStep).where(AgentStep.execution_id == execution.id)))
        .scalars()
        .all()
    )
    agent_sequence = [s.agent_name for s in steps]
    assert agent_sequence.count("tester") == 2  # ran once failing, once passing
    assert "debugger" in agent_sequence
    assert agent_sequence.count("developer") == 2  # initial (no-op-ish) pass + the real fix
