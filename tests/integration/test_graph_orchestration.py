"""Phase 2.1 — stateful, bounded orchestration behavior exercised through
the real graph, real workspace, and real persistence: the debug loop
actually recovering, repeated failure terminating exactly at the
configured retry budget (never looping forever even far beyond it),
state (including the new explicit `debug_result`) surviving the full
retry chain, an honest failure when no LLM is configured, cancellation
taking effect mid-execution (not just before the first node), and the
outer LangGraph recursion-limit safety net actually firing.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from agents.graph import GraphDependencies, build_graph
from agents.schemas import DebugResult, DeveloperPlan, Plan, ReviewResult, TestResult
from agents.state import ExecutionState
from backend.app.db.models.agent_step import AgentStep
from backend.app.db.repositories.executions import create_execution
from backend.app.db.repositories.projects import create_project
from rag.embeddings.hashing_provider import HashingEmbeddingProvider
from tests.fakes import FakeStructuredLLMClient
from tools.registry import build_default_registry
from tools.terminal.contract import TerminalCommandResult
from tools.terminal.tools import ExecuteTerminalCommandTool
from tools.workspace import Workspace


def _make_test_command_succeed_at_the_tool_layer(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tester only asks the LLM to interpret a `TestResult` once a real
    command execution actually reports `status="success"` (see
    `agents/tester.py`) — otherwise it honestly reports "unavailable"
    without ever consulting the LLM. Exercising the debug loop through the
    real graph therefore needs the terminal tool itself to report success
    (a fixed exit code is enough; the *meaning* of pass/fail for these
    tests comes entirely from the scripted `TestResult` responses handed
    to `FakeStructuredLLMClient`, not from this canned exit code), without
    requiring a live Docker sandbox — Docker availability is an
    environment fact, not something a deterministic unit/integration test
    should depend on.
    """

    async def fake_run(self, tool_input, context):  # noqa: ANN001 - matches Tool.run's signature
        return TerminalCommandResult(
            command=tool_input.command,
            exit_code=0,
            stdout="",
            stderr="",
            stdout_truncated=False,
            stderr_truncated=False,
            timed_out=False,
            duration_ms=1,
        )

    monkeypatch.setattr(ExecuteTerminalCommandTool, "run", fake_run)


async def _agent_step_names_in_order(db_session, execution_id) -> list[str]:
    steps = (
        (
            await db_session.execute(
                select(AgentStep).where(AgentStep.execution_id == execution_id).order_by(AgentStep.created_at)
            )
        )
        .scalars()
        .all()
    )
    return [s.agent_name for s in steps]


async def test_debug_path_recovers_and_reaches_reviewer(
    db_session, tmp_git_workspace: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Planner -> Developer -> Tester FAIL -> Debugger -> Developer ->
    Tester PASS -> Reviewer -> finalize, with real AgentStep rows for the
    whole path and important state surviving the round trip."""
    _make_test_command_succeed_at_the_tool_layer(monkeypatch)
    (tmp_git_workspace.root / "pyproject.toml").write_text("[project]\nname = \"sample\"\n", encoding="utf-8")

    project = await create_project(db_session, name=f"proj-{uuid.uuid4()}", workspace_path=str(tmp_git_workspace.root))
    execution = await create_execution(db_session, project_id=project.id, task="fix the bug")

    llm = FakeStructuredLLMClient(
        {
            "Plan": Plan(objective="fix it", steps=["find and fix the bug"], testing_strategy="pytest"),
            "DeveloperPlan": DeveloperPlan(summary="applied a fix"),
            "TestResult": [
                TestResult(status="failed", summary="1 failed", errors=["AssertionError: boom"]),
                TestResult(status="passed", summary="1 passed"),
            ],
            "DebugResult": DebugResult(
                root_cause="off-by-one error", proposed_fix="use <= instead of <", confidence="high",
                files_to_change=["calc.py"],
            ),
            "ReviewResult": ReviewResult(verdict="approved", summary="looks correct now"),
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
        user_task="fix the bug",
        workspace_root=str(tmp_git_workspace.root),
    )
    final = await graph.ainvoke(initial_state)

    assert final["execution_status"] == "passed"
    assert final["retry_count"] == 1
    assert final["test_results"].status == "passed"
    assert final["debug_result"].root_cause == "off-by-one error"
    # Preserved from the very first turn, all the way through the loop.
    assert final["plan"].objective == "fix it"

    names = await _agent_step_names_in_order(db_session, execution.id)
    assert names == ["planner", "developer", "tester", "debugger", "developer", "tester", "reviewer"]


async def test_repeated_failure_terminates_exactly_at_configured_retry_limit(
    db_session, tmp_git_workspace: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Tester fails every single time (Debugger's fix never actually
    works) — the graph must still terminate deterministically, exactly
    once the configured retry budget is spent, never looping forever."""
    _make_test_command_succeed_at_the_tool_layer(monkeypatch)
    (tmp_git_workspace.root / "pyproject.toml").write_text("[project]\nname = \"sample\"\n", encoding="utf-8")

    project = await create_project(db_session, name=f"proj-{uuid.uuid4()}", workspace_path=str(tmp_git_workspace.root))
    execution = await create_execution(db_session, project_id=project.id, task="fix the stubborn bug")

    max_debug_retries = 2
    llm = FakeStructuredLLMClient(
        {
            "Plan": Plan(objective="fix it", steps=["investigate"], testing_strategy="pytest"),
            "DeveloperPlan": DeveloperPlan(summary="attempted a fix"),
            # Always failed — the same failure, every single time.
            "TestResult": TestResult(status="failed", summary="still failing", errors=["same assertion"]),
            "DebugResult": DebugResult(
                root_cause="unclear", proposed_fix="try something else", confidence="low", files_to_change=[]
            ),
            # Reviewer approving despite failing tests must still not
            # produce a "passed" execution — proven at the service layer's
            # _map_final_status; here we only need a valid response so
            # Reviewer's own turn completes.
            "ReviewResult": ReviewResult(verdict="approved", summary="reviewed despite failures"),
        }
    )

    deps = GraphDependencies(
        registry=build_default_registry(),
        llm_client=llm,
        embedding_provider=HashingEmbeddingProvider(),
        db=db_session,
        max_debug_retries=max_debug_retries,
    )
    graph = build_graph(deps)

    initial_state = ExecutionState(
        execution_id=str(execution.id),
        project_id=str(project.id),
        user_task="fix the stubborn bug",
        workspace_root=str(tmp_git_workspace.root),
    )
    final = await graph.ainvoke(initial_state, config={"recursion_limit": 50})

    # The graph terminated (this line is only reached if it did) exactly at
    # the configured budget, not one turn earlier or later.
    assert final["retry_count"] == max_debug_retries
    assert final["test_results"].status == "failed"
    assert final["review_result"] is not None  # Reviewer still ran, deterministically, once retries were spent.

    names = await _agent_step_names_in_order(db_session, execution.id)
    assert names == [
        "planner",
        "developer", "tester", "debugger",
        "developer", "tester", "debugger",
        "developer", "tester",
        "reviewer",
    ]
    assert names.count("developer") == max_debug_retries + 1
    assert names.count("tester") == max_debug_retries + 1
    assert names.count("debugger") == max_debug_retries
    assert names.count("reviewer") == 1


async def test_llm_unavailable_is_an_honest_failure_not_fabricated_success(
    db_session, tmp_git_workspace: Workspace
) -> None:
    project = await create_project(db_session, name=f"proj-{uuid.uuid4()}", workspace_path=str(tmp_git_workspace.root))
    execution = await create_execution(db_session, project_id=project.id, task="do something")

    deps = GraphDependencies(
        registry=build_default_registry(), llm_client=None, embedding_provider=HashingEmbeddingProvider(), db=db_session
    )
    graph = build_graph(deps)

    initial_state = ExecutionState(
        execution_id=str(execution.id),
        project_id=str(project.id),
        user_task="do something",
        workspace_root=str(tmp_git_workspace.root),
    )
    final = await graph.ainvoke(initial_state)

    assert final["execution_status"] == "error"
    assert final["final_result"]["status"] == "error"
    assert any("Planner cannot run" in e for e in final["errors"])

    names = await _agent_step_names_in_order(db_session, execution.id)
    assert names == ["planner"]


async def test_cancellation_mid_execution_stops_before_the_next_agent(
    db_session, tmp_git_workspace: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Cancellation requested *after* Planner has already started must
    still be honored before Developer's turn — not just before the very
    first node of the whole run."""
    import agents.graph as graph_module

    project = await create_project(db_session, name=f"proj-{uuid.uuid4()}", workspace_path=str(tmp_git_workspace.root))
    execution = await create_execution(db_session, project_id=project.id, task="add a file")

    call_count = {"n": 0}
    real_is_cancelled = graph_module.is_cancelled

    def fake_is_cancelled(execution_id):
        call_count["n"] += 1
        # Not cancelled for orchestrator/planner's checks; cancelled from
        # the third check (Developer's turn) onward.
        return call_count["n"] > 2

    monkeypatch.setattr(graph_module, "is_cancelled", fake_is_cancelled)

    llm = FakeStructuredLLMClient(
        {"Plan": Plan(objective="add file", steps=["write it"], testing_strategy="manual")}
    )
    deps = GraphDependencies(
        registry=build_default_registry(), llm_client=llm, embedding_provider=HashingEmbeddingProvider(), db=db_session
    )
    graph = build_graph(deps)

    initial_state = ExecutionState(
        execution_id=str(execution.id),
        project_id=str(project.id),
        user_task="add a file",
        workspace_root=str(tmp_git_workspace.root),
    )
    final = await graph.ainvoke(initial_state)

    assert final["execution_status"] == "cancelled"
    assert final["final_result"]["status"] == "cancelled"

    # Planner genuinely ran (it's in the AgentStep history); Developer,
    # scoped by the fake to look cancelled, never did.
    names = await _agent_step_names_in_order(db_session, execution.id)
    assert names == ["planner"]
    assert real_is_cancelled is not None  # sanity: we did capture the real function above


async def test_graph_recursion_limit_is_a_hard_backstop_beyond_the_retry_budget(
    db_session, tmp_git_workspace: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Even with an absurdly generous debug-retry budget (so the retry
    budget itself never trips), LangGraph's own recursion_limit —
    configurable via MAX_AGENT_TURNS — is a second, independent ceiling
    that stops a genuinely-looping debug cycle (Tester really does fail
    every time here) from running away."""
    from langgraph.errors import GraphRecursionError

    _make_test_command_succeed_at_the_tool_layer(monkeypatch)
    (tmp_git_workspace.root / "pyproject.toml").write_text("[project]\nname = \"sample\"\n", encoding="utf-8")

    project = await create_project(db_session, name=f"proj-{uuid.uuid4()}", workspace_path=str(tmp_git_workspace.root))
    execution = await create_execution(db_session, project_id=project.id, task="fix it")

    llm = FakeStructuredLLMClient(
        {
            "Plan": Plan(objective="fix it", steps=["investigate"], testing_strategy="pytest"),
            "DeveloperPlan": DeveloperPlan(summary="attempted a fix"),
            "TestResult": TestResult(status="failed", summary="still failing"),
            "DebugResult": DebugResult(root_cause="?", proposed_fix="?", confidence="low", files_to_change=[]),
            "ReviewResult": ReviewResult(verdict="changes_required", summary="not fixed"),
        }
    )

    deps = GraphDependencies(
        registry=build_default_registry(),
        llm_client=llm,
        embedding_provider=HashingEmbeddingProvider(),
        db=db_session,
        max_debug_retries=1000,  # effectively "never trip" for this test
    )
    graph = build_graph(deps)

    initial_state = ExecutionState(
        execution_id=str(execution.id),
        project_id=str(project.id),
        user_task="fix it",
        workspace_root=str(tmp_git_workspace.root),
    )

    # One full debug cycle is 3 turns (developer, tester, debugger); a
    # limit of 10 permits the initial planner/developer/tester/debugger
    # turns plus one more full cycle but not the several more it would
    # take to ever reach Reviewer through this always-failing Tester.
    with pytest.raises(GraphRecursionError):
        await graph.ainvoke(initial_state, config={"recursion_limit": 10})
