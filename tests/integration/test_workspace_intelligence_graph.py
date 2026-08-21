"""Phase 2.2 — workspace/repository intelligence exercised through the
real graph: the Orchestrator builds a structured `ProjectContext` before
Planner ever runs, Planner's prompt is genuinely grounded in it (not just
carrying it through unused), that context survives the full
Orchestrator -> Planner -> Developer chain, and a failure inside repository
analysis degrades gracefully (a warning, not a fabricated understanding
and not an aborted execution) exactly as Phase 2.1's other bounded-failure
paths do for the rest of the pipeline.
"""

from __future__ import annotations

import uuid

import pytest

import analysis.context as context_module
from agents.graph import GraphDependencies, build_graph
from agents.schemas import DeveloperPlan, Plan, ReviewResult, TestResult
from agents.state import ExecutionState
from backend.app.db.repositories.executions import create_execution
from backend.app.db.repositories.projects import create_project
from rag.embeddings.hashing_provider import HashingEmbeddingProvider
from tests.fakes import FakeStructuredLLMClient
from tools.registry import build_default_registry
from tools.workspace import Workspace


def _fastapi_workspace(tmp_git_workspace: Workspace) -> Workspace:
    (tmp_git_workspace.root / "pyproject.toml").write_text(
        '[project]\nname = "demo"\ndependencies = [\n    "fastapi>=0.115",\n]\n'
    )
    (tmp_git_workspace.root / "backend" / "app").mkdir(parents=True)
    (tmp_git_workspace.root / "backend" / "app" / "auth_service.py").write_text("def login(): pass\n")
    return tmp_git_workspace


async def test_planner_prompt_is_grounded_in_the_orchestrators_project_context(
    db_session, tmp_git_workspace: Workspace
) -> None:
    _fastapi_workspace(tmp_git_workspace)
    project = await create_project(db_session, name=f"proj-{uuid.uuid4()}", workspace_path=str(tmp_git_workspace.root))
    execution = await create_execution(db_session, project_id=project.id, task="Fix authentication bug")

    llm = FakeStructuredLLMClient(
        {
            "Plan": Plan(objective="fix it", steps=["find the bug"], testing_strategy="pytest"),
            "DeveloperPlan": DeveloperPlan(summary="looked around"),
            "TestResult": TestResult(status="unavailable", summary="no test command found"),
            "ReviewResult": ReviewResult(verdict="approved", summary="fine"),
        }
    )
    deps = GraphDependencies(
        registry=build_default_registry(), llm_client=llm, embedding_provider=HashingEmbeddingProvider(), db=db_session
    )
    graph = build_graph(deps)

    initial_state = ExecutionState(
        execution_id=str(execution.id),
        project_id=str(project.id),
        user_task="Fix authentication bug",
        workspace_root=str(tmp_git_workspace.root),
    )
    final = await graph.ainvoke(initial_state)

    assert final["project_context"] is not None
    assert final["project_context"].languages == ["Python"]
    assert "FastAPI" in final["project_context"].frameworks

    planner_calls = [c for c in llm.calls if c[2] is Plan]
    assert len(planner_calls) == 1
    planner_prompt = planner_calls[0][1]
    assert "FastAPI" in planner_prompt
    assert "Python" in planner_prompt
    assert "auth_service.py" in planner_prompt


async def test_project_context_survives_orchestrator_planner_developer(
    db_session, tmp_git_workspace: Workspace
) -> None:
    _fastapi_workspace(tmp_git_workspace)
    project = await create_project(db_session, name=f"proj-{uuid.uuid4()}", workspace_path=str(tmp_git_workspace.root))
    execution = await create_execution(db_session, project_id=project.id, task="Fix authentication bug")

    llm = FakeStructuredLLMClient(
        {
            "Plan": Plan(objective="fix it", steps=["find the bug"], testing_strategy="pytest"),
            "DeveloperPlan": DeveloperPlan(summary="looked around"),
            "TestResult": TestResult(status="unavailable", summary="no test command found"),
            "ReviewResult": ReviewResult(verdict="approved", summary="fine"),
        }
    )
    deps = GraphDependencies(
        registry=build_default_registry(), llm_client=llm, embedding_provider=HashingEmbeddingProvider(), db=db_session
    )
    graph = build_graph(deps)

    initial_state = ExecutionState(
        execution_id=str(execution.id),
        project_id=str(project.id),
        user_task="Fix authentication bug",
        workspace_root=str(tmp_git_workspace.root),
    )
    final = await graph.ainvoke(initial_state)

    # Reached Developer and beyond (state didn't get reset/dropped along
    # the way) with the same project_context still attached.
    assert final["plan"] is not None
    assert final["project_context"] is not None
    assert final["project_context"].languages == ["Python"]


async def test_repository_analysis_failure_degrades_gracefully_not_fatally(
    db_session, tmp_git_workspace: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A broken analysis stage must not fabricate a project understanding
    and must not abort the whole execution either — Planner still runs,
    just with an explicitly incomplete/absent project context."""

    def _boom(*args, **kwargs):
        raise RuntimeError("simulated repository scan failure")

    monkeypatch.setattr(context_module, "scan_repository", _boom)

    project = await create_project(db_session, name=f"proj-{uuid.uuid4()}", workspace_path=str(tmp_git_workspace.root))
    execution = await create_execution(db_session, project_id=project.id, task="Fix authentication bug")

    llm = FakeStructuredLLMClient(
        {
            "Plan": Plan(objective="fix it", steps=["find the bug"], testing_strategy="pytest"),
            "DeveloperPlan": DeveloperPlan(summary="looked around"),
            "TestResult": TestResult(status="unavailable", summary="no test command found"),
            "ReviewResult": ReviewResult(verdict="approved", summary="fine"),
        }
    )
    deps = GraphDependencies(
        registry=build_default_registry(), llm_client=llm, embedding_provider=HashingEmbeddingProvider(), db=db_session
    )
    graph = build_graph(deps)

    initial_state = ExecutionState(
        execution_id=str(execution.id),
        project_id=str(project.id),
        user_task="Fix authentication bug",
        workspace_root=str(tmp_git_workspace.root),
    )
    final = await graph.ainvoke(initial_state)

    assert final["project_context"] is not None
    assert final["project_context"].incomplete is True
    assert final["project_context"].languages == []
    # The execution still proceeded to a real plan, not an aborted run.
    assert final["plan"] is not None
    assert final["execution_status"] not in ("error",)
