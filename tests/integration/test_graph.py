from __future__ import annotations

import uuid

from sqlalchemy import select

from agents.graph import GraphDependencies, build_graph
from agents.llm_client import MalformedLLMOutputError
from agents.schemas import DeveloperPlan, Plan, ReviewResult
from agents.state import ExecutionState
from backend.app.db.models.agent_step import AgentStep, AgentStepStatus
from backend.app.db.repositories.executions import create_execution
from backend.app.db.repositories.projects import create_project
from rag.embeddings.hashing_provider import HashingEmbeddingProvider
from tests.fakes import FakeStructuredLLMClient
from tools.registry import build_default_registry
from tools.workspace import Workspace


def test_graph_construction_has_expected_nodes() -> None:
    deps = GraphDependencies(
        registry=build_default_registry(), llm_client=None, embedding_provider=HashingEmbeddingProvider()
    )
    graph = build_graph(deps)
    nodes = set(graph.get_graph().nodes.keys())
    assert {"orchestrator", "planner", "developer", "tester", "debugger", "reviewer", "finalize"} <= nodes


async def test_graph_happy_path_reaches_reviewer_and_persists_agent_steps(
    db_session, tmp_git_workspace: Workspace
) -> None:
    project = await create_project(
        db_session, name=f"proj-{uuid.uuid4()}", workspace_path=str(tmp_git_workspace.root)
    )
    execution = await create_execution(db_session, project_id=project.id, task="add a hello file")

    llm = FakeStructuredLLMClient(
        {
            "Plan": Plan(objective="add hello", steps=["write hello.txt"], testing_strategy="manual"),
            "DeveloperPlan": DeveloperPlan(summary="created hello.txt"),
            "ReviewResult": ReviewResult(verdict="approved", summary="looks fine"),
        },
        tool_call_scripts=[[("write_file", {"path": "hello.txt", "content": "hi"})]],
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
        user_task="add a hello file",
        workspace_root=str(tmp_git_workspace.root),
    )
    final = await graph.ainvoke(initial_state)

    assert final["execution_status"] == "passed"
    assert final["review_result"].verdict == "approved"
    assert final["final_result"]["status"] == "passed"
    assert (tmp_git_workspace.root / "hello.txt").exists()

    steps = (
        (await db_session.execute(select(AgentStep).where(AgentStep.execution_id == execution.id)))
        .scalars()
        .all()
    )
    agent_names = {s.agent_name for s in steps}
    assert agent_names == {"planner", "developer", "tester", "reviewer"}
    assert all(s.status == AgentStepStatus.SUCCEEDED.value for s in steps)


async def test_graph_records_hard_failure_as_error_and_stops_early(
    db_session, tmp_git_workspace: Workspace
) -> None:
    project = await create_project(
        db_session, name=f"proj-{uuid.uuid4()}", workspace_path=str(tmp_git_workspace.root)
    )
    execution = await create_execution(db_session, project_id=project.id, task="add a hello file")

    llm = FakeStructuredLLMClient({"Plan": MalformedLLMOutputError("planner returned garbage")})

    deps = GraphDependencies(
        registry=build_default_registry(),
        llm_client=llm,
        embedding_provider=HashingEmbeddingProvider(),
        db=db_session,
    )
    graph = build_graph(deps)

    initial_state = ExecutionState(
        execution_id=str(execution.id),
        project_id=str(project.id),
        user_task="add a hello file",
        workspace_root=str(tmp_git_workspace.root),
    )
    final = await graph.ainvoke(initial_state)

    assert final["execution_status"] == "error"
    assert final["final_result"]["status"] == "error"
    assert any("planner returned garbage" in e for e in final["errors"])

    steps = (
        (await db_session.execute(select(AgentStep).where(AgentStep.execution_id == execution.id)))
        .scalars()
        .all()
    )
    # Only the planner step ran (and failed) — developer/tester/reviewer never started.
    assert {s.agent_name for s in steps} == {"planner"}
    assert steps[0].status == AgentStepStatus.FAILED.value
