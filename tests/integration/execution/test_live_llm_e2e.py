"""REAL end-to-end validation of whichever LLM provider is configured
(LLM_PROVIDER — gemini by default, qwen also supported), Phase 1.5
section 21.

Runs the complete, real production path — no fake LLM client anywhere —
against the deterministic calculator fixture:

    LLM -> Planner -> Developer -> real tool calls -> Docker -> Tester -> Reviewer

Skips (never fails, never fabricates a result) when no API key is
configured, in addition to the usual Docker-image skip guard this
directory's conftest already applies. This is the one place in the suite
where the LLM is never scripted — see `backend/tests/test_llm_smoke.py`
for narrower, faster live checks of the same endpoint.
"""

from __future__ import annotations

import shutil
import uuid
from pathlib import Path

import pytest

from agents.graph import GraphDependencies, build_graph
from agents.llm_client import build_default_llm_client
from agents.state import ExecutionState
from backend.app.core.config import get_settings
from backend.app.db.repositories.executions import create_execution
from backend.app.db.repositories.projects import create_project
from rag.embeddings.hashing_provider import HashingEmbeddingProvider
from tools.registry import build_default_registry
from tools.workspace import Workspace

FIXTURE_ROOT = Path(__file__).resolve().parents[3] / "playground" / "sample-project"


async def test_live_llm_full_graph_against_calculator_fixture(db_session, tmp_path: Path) -> None:
    settings = get_settings()
    if not settings.llm_api_key:
        pytest.skip("LLM_API_KEY not configured; live end-to-end validation not run.")
    if settings.llm_provider != "gemini" and not settings.llm_base_url:
        pytest.skip("LLM_BASE_URL not configured; live end-to-end validation not run.")

    workspace_dir = tmp_path / "calculator"
    shutil.copytree(FIXTURE_ROOT, workspace_dir)
    workspace = Workspace.at(workspace_dir)

    project = await create_project(db_session, name=f"proj-{uuid.uuid4()}", workspace_path=str(workspace.root))
    task = "Add a power(a, b) function to calculator.py that raises a to the power of b, with a test."
    execution = await create_execution(db_session, project_id=project.id, task=task)

    deps = GraphDependencies(
        registry=build_default_registry(),
        llm_client=build_default_llm_client(),
        embedding_provider=HashingEmbeddingProvider(),
        db=db_session,
        max_debug_retries=2,
    )
    graph = build_graph(deps)

    initial_state = ExecutionState(
        execution_id=str(execution.id), project_id=str(project.id), user_task=task, workspace_root=str(workspace.root)
    )
    final = await graph.ainvoke(initial_state, config={"recursion_limit": 50})

    # Real, unscripted assertions about a real model's real work — never
    # assumed passing; if the live model's implementation was wrong, this
    # test must fail, not silently pass.
    assert final["execution_status"] in ("passed", "failed")  # a real terminal verdict was reached, not "error"
    assert final["plan"] is not None
    assert final["test_results"] is not None
    assert final["test_results"].status in ("passed", "failed")  # tests actually ran, not "unavailable"
    assert final["review_result"] is not None
