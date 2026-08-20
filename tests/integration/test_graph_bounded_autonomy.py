"""Execution-wide bounded-autonomy behavior: the total tool-call budget
and cancellation, both exercised through the real graph against a real
workspace and real tool registry."""

from __future__ import annotations

import uuid

from agents.graph import GraphDependencies, build_graph
from agents.schemas import DeveloperPlan, Plan, ReviewResult
from agents.state import ExecutionState
from backend.app.db.repositories.executions import create_execution
from backend.app.db.repositories.projects import create_project
from backend.app.services.cancellation import clear_cancellation, is_cancelled, request_cancellation
from rag.embeddings.hashing_provider import HashingEmbeddingProvider
from tests.fakes import FakeStructuredLLMClient
from tools.registry import build_default_registry
from tools.workspace import Workspace


async def test_max_total_tool_calls_caps_developer_budget_across_the_run(
    db_session, tmp_git_workspace: Workspace
) -> None:
    project = await create_project(
        db_session, name=f"proj-{uuid.uuid4()}", workspace_path=str(tmp_git_workspace.root)
    )
    execution = await create_execution(db_session, project_id=project.id, task="add two files")

    llm = FakeStructuredLLMClient(
        {
            "Plan": Plan(objective="add files", steps=["add a.txt and b.txt"], testing_strategy="manual"),
            "DeveloperPlan": DeveloperPlan(summary="wrote as many files as allowed"),
            "ReviewResult": ReviewResult(verdict="approved", summary="ok"),
        },
        tool_call_scripts=[
            [
                ("write_file", {"path": "a.txt", "content": "1"}),
                ("write_file", {"path": "b.txt", "content": "2"}),
            ]
        ],
    )

    deps = GraphDependencies(
        registry=build_default_registry(),
        llm_client=llm,
        embedding_provider=HashingEmbeddingProvider(),
        db=db_session,
        max_total_tool_calls=1,
        max_tool_calls_per_agent=12,
    )
    graph = build_graph(deps)

    initial_state = ExecutionState(
        execution_id=str(execution.id),
        project_id=str(project.id),
        user_task="add two files",
        workspace_root=str(tmp_git_workspace.root),
    )
    final = await graph.ainvoke(initial_state)

    # Only the first scripted tool call fit inside the execution-wide budget.
    assert len(final["tool_calls"]) == 1
    assert (tmp_git_workspace.root / "a.txt").exists()
    assert not (tmp_git_workspace.root / "b.txt").exists()


async def test_cancellation_is_honored_before_the_next_agent_turn(
    db_session, tmp_git_workspace: Workspace
) -> None:
    project = await create_project(
        db_session, name=f"proj-{uuid.uuid4()}", workspace_path=str(tmp_git_workspace.root)
    )
    execution = await create_execution(db_session, project_id=project.id, task="add a file")

    # No responses configured — if any agent actually ran, the fake would
    # raise on the first unconfigured request, failing the test loudly.
    llm = FakeStructuredLLMClient()

    deps = GraphDependencies(
        registry=build_default_registry(), llm_client=llm, embedding_provider=HashingEmbeddingProvider(), db=db_session
    )
    graph = build_graph(deps)

    request_cancellation(execution.id)
    try:
        initial_state = ExecutionState(
            execution_id=str(execution.id),
            project_id=str(project.id),
            user_task="add a file",
            workspace_root=str(tmp_git_workspace.root),
        )
        final = await graph.ainvoke(initial_state)

        assert final["execution_status"] == "cancelled"
        assert final["final_result"]["status"] == "cancelled"
    finally:
        clear_cancellation(execution.id)


def test_cancellation_registry_request_and_clear() -> None:
    execution_id = uuid.uuid4()
    assert is_cancelled(execution_id) is False
    request_cancellation(execution_id)
    assert is_cancelled(execution_id) is True
    clear_cancellation(execution_id)
    assert is_cancelled(execution_id) is False
