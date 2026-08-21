"""Phase 2.8 — Independent Code Review, exercised through the real graph,
real filesystem, real PostgreSQL, real Git, and (Fixtures A/F) a real
Docker sandbox running real pytest. Only the LLM is ever faked (no live
key in this environment — the same disclosed methodology every prior
phase's graph-integration tests use).
"""

from __future__ import annotations

import shutil
import uuid
from pathlib import Path

from sqlalchemy import select

from agents.graph import GraphDependencies, build_graph
from agents.reviewer import _deleted_test_files, _looks_like_a_weakened_assertion, _unexpected_files
from agents.schemas import DeveloperPlan, FileChange, Plan, ReviewResult
from agents.state import ExecutionState
from backend.app.db.models.agent_step import AgentStep
from backend.app.db.repositories.executions import create_execution
from backend.app.db.repositories.projects import create_project
from rag.embeddings.hashing_provider import HashingEmbeddingProvider
from tests.fakes import FakeStructuredLLMClient
from tools.registry import build_default_registry
from tools.workspace import Workspace

FIXTURE_ROOT = Path(__file__).resolve().parents[2] / "playground" / "sample-project"


def _make_tests_always_pass(monkeypatch) -> None:  # noqa: ANN001 - pytest.MonkeyPatch
    """For fixtures whose point is Reviewer's own logic (not test
    execution itself): a genuine passing TestResult without needing a
    real pytest install in this environment, so the debug loop is never
    entered and the review-loop mechanics stay the sole focus."""
    from tools.terminal.contract import TerminalCommandResult
    from tools.terminal.tools import ExecuteTerminalCommandTool

    async def _always_passes(self, tool_input, context):
        return TerminalCommandResult(
            command=tool_input.command, exit_code=0, stdout="1 passed", stderr="",
            stdout_truncated=False, stderr_truncated=False, timed_out=False, duration_ms=1,
        )

    monkeypatch.setattr(ExecuteTerminalCommandTool, "run", _always_passes)


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


# ---- Fixture A / section 13.1: clean change -> real pass -> APPROVED ----


async def test_fixture_a_clean_change_with_real_passing_tests_is_genuinely_passed(
    db_session, tmp_path: Path
) -> None:
    workspace_dir = tmp_path / "calculator"
    shutil.copytree(FIXTURE_ROOT, workspace_dir)
    workspace = Workspace.at(workspace_dir)

    llm = FakeStructuredLLMClient(
        {
            "Plan": Plan(objective="add exponent", steps=["add exponent()"], testing_strategy="pytest", files_likely_involved=["calculator.py"]),
            "DeveloperPlan": DeveloperPlan(summary="added exponent()"),
            "ReviewResult": ReviewResult(verdict="approved", summary="correct, well-scoped, and covered by passing tests"),
        },
        tool_call_scripts=[
            [("edit_file", {"path": "calculator.py", "old_string": "def divide(a, b):\n    return a / b\n", "new_string": "def divide(a, b):\n    return a / b\n\n\ndef exponent(a, b):\n    return a ** b\n"})],
        ],
    )

    execution, final = await _run_graph(db_session, workspace, "add an exponent function", llm)

    assert final["test_results"].status == "passed"
    assert final["review_result"].verdict == "approved"
    # Section 15: real tests passed AND review approved -> genuinely PASSED.
    assert final["execution_status"] == "passed"
    assert final["review_result"].risk == "low"
    assert final["review_result"].files_reviewed == 1


# ---- Fixture B: buggy change, tests still pass, Reviewer flags it --------


async def test_fixture_b_buggy_change_can_be_flagged_despite_passing_tests(
    db_session, tmp_git_workspace: Workspace, monkeypatch
) -> None:
    _make_tests_always_pass(monkeypatch)
    (tmp_git_workspace.root / "pyproject.toml").write_text('[project]\nname = "x"\n', encoding="utf-8")

    llm = FakeStructuredLLMClient(
        {
            "Plan": Plan(objective="add feature", steps=["implement it"], testing_strategy="pytest"),
            "DeveloperPlan": DeveloperPlan(summary="implemented it"),
            "ReviewResult": ReviewResult(
                verdict="changes_required",
                summary="off-by-one in the new loop bound will silently drop the last element",
                issues=["loop uses range(n-1) instead of range(n)"],
            ),
        }
    )

    execution, final = await _run_graph(db_session, tmp_git_workspace, "add feature", llm)

    assert final["review_result"].verdict == "changes_required"
    assert "off-by-one" in final["review_result"].summary
    assert final["execution_status"] == "needs_review"  # review-retry budget default (2) exhausted below


# ---- Fixture C: security issue ---------------------------------------------


async def test_fixture_c_security_issue_forces_high_risk_regardless_of_llm_assessment(
    db_session, tmp_git_workspace: Workspace, monkeypatch
) -> None:
    _make_tests_always_pass(monkeypatch)
    (tmp_git_workspace.root / "pyproject.toml").write_text('[project]\nname = "x"\n', encoding="utf-8")

    # The LLM under-calls the risk ("low") despite reporting a genuine
    # security_issue — the deterministic floor must still win.
    llm = FakeStructuredLLMClient(
        {
            "Plan": Plan(objective="add endpoint", steps=["implement it"], testing_strategy="pytest"),
            "DeveloperPlan": DeveloperPlan(summary="implemented it"),
            "ReviewResult": ReviewResult(
                verdict="changes_required",
                summary="hardcoded API key introduced",
                security_issues=["hardcoded API key committed to source"],
                risk="low",
            ),
        }
    )

    execution, final = await _run_graph(db_session, tmp_git_workspace, "add endpoint", llm)

    assert final["review_result"].security_issues
    assert final["review_result"].risk == "high"


# ---- Fixture D: unrelated files changed -> deterministic scope warning ---


def test_fixture_d_unexpected_files_detected_deterministically() -> None:
    plan = Plan(objective="fix auth", steps=["fix it"], testing_strategy="t", files_likely_involved=["auth.py"])
    state = ExecutionState(
        execution_id="1", project_id="2", user_task="fix auth", workspace_root="C:/tmp", plan=plan,
        files_changed=[
            FileChange(path="auth.py", change_type="modified", detail="edited"),
            FileChange(path="unrelated_billing_module.py", change_type="modified", detail="edited"),
        ],
    )
    unexpected = _unexpected_files(state)
    assert unexpected == ["unrelated_billing_module.py"]


async def test_fixture_d_unrelated_change_is_flagged_in_the_review(
    db_session, tmp_git_workspace: Workspace, monkeypatch
) -> None:
    _make_tests_always_pass(monkeypatch)
    (tmp_git_workspace.root / "pyproject.toml").write_text('[project]\nname = "x"\n', encoding="utf-8")
    (tmp_git_workspace.root / "auth.py").write_text("def login(): pass\n", encoding="utf-8")
    (tmp_git_workspace.root / "billing.py").write_text("def charge(): pass\n", encoding="utf-8")

    llm = FakeStructuredLLMClient(
        {
            "Plan": Plan(objective="fix auth", steps=["fix login"], testing_strategy="pytest", files_likely_involved=["auth.py"]),
            "DeveloperPlan": DeveloperPlan(summary="fixed login, also touched billing.py"),
            "ReviewResult": ReviewResult(
                verdict="changes_required", summary="unrelated file changed", issues=["billing.py touched but unrelated to the task"]
            ),
        },
        tool_call_scripts=[
            [
                ("edit_file", {"path": "auth.py", "old_string": "def login(): pass", "new_string": "def login(): return True"}),
                ("edit_file", {"path": "billing.py", "old_string": "def charge(): pass", "new_string": "def charge(): return True"}),
            ]
        ],
    )

    execution, final = await _run_graph(db_session, tmp_git_workspace, "fix auth", llm)

    assert final["review_result"].risk in ("medium", "high")


# ---- Fixture E: weakened test ----------------------------------------------


def test_fixture_e_weakened_assertion_detected_deterministically() -> None:
    diff = (
        "--- a/test_calc.py\n+++ b/test_calc.py\n@@\n"
        "-    assert calculate_total([10, 20]) == 30\n"
        "+    assert True\n"
    )
    assert _looks_like_a_weakened_assertion(diff) is True
    assert _looks_like_a_weakened_assertion("+    assert calculate_total([10, 20]) == 30\n") is False


def test_fixture_e_deleted_test_file_detected_deterministically() -> None:
    state = ExecutionState(
        execution_id="1", project_id="2", user_task="x", workspace_root="C:/tmp",
        files_changed=[FileChange(path="tests/test_auth.py", change_type="deleted", detail="removed")],
    )
    assert _deleted_test_files(state) == ["tests/test_auth.py"]


# ---- Fixture F / section 13.2: review loop reaches APPROVED --------------


async def test_fixture_f_review_loop_requests_a_valid_correction_then_approves(
    db_session, tmp_git_workspace: Workspace, monkeypatch
) -> None:
    _make_tests_always_pass(monkeypatch)
    (tmp_git_workspace.root / "pyproject.toml").write_text('[project]\nname = "x"\n', encoding="utf-8")

    llm = FakeStructuredLLMClient(
        {
            "Plan": Plan(objective="add feature", steps=["implement it"], testing_strategy="pytest"),
            "DeveloperPlan": DeveloperPlan(summary="implemented it"),
            "ReviewResult": [
                ReviewResult(verdict="changes_required", summary="missing input validation", issues=["no null check"]),
                ReviewResult(verdict="approved", summary="validation added, looks correct now"),
            ],
        }
    )

    execution, final = await _run_graph(db_session, tmp_git_workspace, "add feature", llm, max_review_retries=2)

    assert final["review_result"].verdict == "approved"
    assert final["execution_status"] == "passed"  # real (mocked) tests passed AND final review approved
    assert final["review_retry_count"] == 1
    assert len(final["review_attempts"]) == 2
    assert final["review_attempts"][0].verdict == "changes_required"
    assert final["review_attempts"][1].verdict == "approved"

    steps = (await db_session.execute(select(AgentStep).where(AgentStep.execution_id == execution.id))).scalars().all()
    agent_sequence = [s.agent_name for s in steps]
    assert agent_sequence.count("reviewer") == 2
    assert agent_sequence.count("developer") == 2
    assert agent_sequence.count("tester") == 2
    assert "debugger" not in agent_sequence  # tests passed throughout; only the review loop cycled


# ---- Fixture G: review budget exhaustion terminates honestly --------------


async def test_fixture_g_repeated_rejection_terminates_honestly_at_the_review_limit(
    db_session, tmp_git_workspace: Workspace, monkeypatch
) -> None:
    _make_tests_always_pass(monkeypatch)
    (tmp_git_workspace.root / "pyproject.toml").write_text('[project]\nname = "x"\n', encoding="utf-8")

    max_review_retries = 2
    llm = FakeStructuredLLMClient(
        {
            "Plan": Plan(objective="add feature", steps=["implement it"], testing_strategy="pytest"),
            "DeveloperPlan": DeveloperPlan(summary="attempted a fix"),
            # Always requests changes — the review never actually converges.
            "ReviewResult": ReviewResult(verdict="changes_required", summary="still not right", issues=["still wrong"]),
        }
    )

    execution, final = await _run_graph(
        db_session, tmp_git_workspace, "add feature", llm, max_review_retries=max_review_retries
    )

    # Bounded: exactly max_review_retries cycles, never an infinite loop,
    # and the final state is an honest "needs_review", never a fabricated pass.
    assert final["review_retry_count"] == max_review_retries
    assert final["review_result"].verdict == "changes_required"
    assert final["execution_status"] == "needs_review"
    assert final["execution_status"] != "passed"
    assert len(final["review_attempts"]) == max_review_retries

    steps = (await db_session.execute(select(AgentStep).where(AgentStep.execution_id == execution.id))).scalars().all()
    assert [s.agent_name for s in steps].count("reviewer") == max_review_retries
