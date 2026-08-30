"""Phase 8: the finalize node records a real Playwright screenshot
(`TestResult.screenshot_path`) as a genuine execution artifact — proof of
work the UI can actually render (see agents/graph.py's finalize node and
frontend/features/execution/RuntimePanel.tsx) — independent of
`Plan.expected_artifact_glob`, since a screenshot is platform-generated
verification evidence, not something the Developer wrote or the Planner
predicted."""

from __future__ import annotations

import uuid

from agents.graph import GraphDependencies, make_finalize_node
from agents.schemas import ReviewResult, TestResult
from agents.state import ExecutionState
from backend.app.db.repositories.artifacts import list_artifacts_for_execution
from backend.app.db.repositories.executions import create_execution
from backend.app.db.repositories.projects import create_project
from rag.embeddings.hashing_provider import HashingEmbeddingProvider
from tools.registry import build_default_registry
from tools.workspace import Workspace


async def _execution_id(db_session, tmp_workspace: Workspace) -> uuid.UUID:
    project = await create_project(db_session, name=f"proj-{uuid.uuid4()}", workspace_path=str(tmp_workspace.root))
    execution = await create_execution(db_session, project_id=project.id, task="build a site")
    return execution.id


def _deps(db_session) -> GraphDependencies:
    return GraphDependencies(
        registry=build_default_registry(), llm_client=None, embedding_provider=HashingEmbeddingProvider(), db=db_session
    )


def _state(execution_id: uuid.UUID, workspace_root: str, test_results: TestResult) -> ExecutionState:
    return ExecutionState(
        execution_id=str(execution_id),
        project_id="p",
        user_task="build a site",
        workspace_root=workspace_root,
        test_results=test_results,
        review_result=ReviewResult(verdict="approved", summary="looks good"),
    )


async def test_finalize_records_screenshot_as_artifact_when_present(db_session, tmp_workspace: Workspace) -> None:
    execution_id = await _execution_id(db_session, tmp_workspace)
    (tmp_workspace.root / ".locopilot").mkdir()
    (tmp_workspace.root / ".locopilot" / "verification-screenshot.png").write_bytes(b"fake-png-bytes")

    test_results = TestResult(
        status="passed",
        summary="ok",
        verification_kind="static_site",
        visual_verification_kind="browser",
        visual_ok=True,
        screenshot_path=".locopilot/verification-screenshot.png",
    )
    node = make_finalize_node(_deps(db_session))
    result = await node(_state(execution_id, str(tmp_workspace.root), test_results))

    assert result["final_result"]["artifact_count"] == 1
    artifacts = await list_artifacts_for_execution(db_session, execution_id)
    screenshots = [a for a in artifacts if a.artifact_type == "screenshot"]
    assert len(screenshots) == 1
    assert screenshots[0].path == ".locopilot/verification-screenshot.png"
    assert screenshots[0].artifact_metadata["visual_ok"] is True


async def test_finalize_records_screenshot_even_when_review_requires_changes(db_session, tmp_workspace: Workspace) -> None:
    """A screenshot is real evidence of what happened regardless of the
    final verdict — useful for diagnosing a needs_review/failed run too,
    not gated on final_status == "passed" the way the glob-based
    project-artifact collection is."""
    execution_id = await _execution_id(db_session, tmp_workspace)
    (tmp_workspace.root / ".locopilot").mkdir()
    (tmp_workspace.root / ".locopilot" / "verification-screenshot.png").write_bytes(b"fake-png-bytes")

    test_results = TestResult(
        status="passed",
        summary="ok",
        verification_kind="static_site",
        visual_verification_kind="browser",
        visual_ok=False,
        visual_reason="Page appears blank.",
        screenshot_path=".locopilot/verification-screenshot.png",
    )
    state = ExecutionState(
        execution_id=str(execution_id),
        project_id="p",
        user_task="build a site",
        workspace_root=str(tmp_workspace.root),
        test_results=test_results,
        review_result=ReviewResult(verdict="changes_required", summary="needs work"),
    )
    node = make_finalize_node(_deps(db_session))
    result = await node(state)

    assert result["final_result"]["status"] != "passed"
    artifacts = await list_artifacts_for_execution(db_session, execution_id)
    assert any(a.artifact_type == "screenshot" for a in artifacts)


async def test_finalize_does_not_record_artifact_when_screenshot_file_missing(db_session, tmp_workspace: Workspace) -> None:
    execution_id = await _execution_id(db_session, tmp_workspace)
    test_results = TestResult(
        status="passed",
        summary="ok",
        verification_kind="static_site",
        visual_verification_kind="browser",
        visual_ok=True,
        screenshot_path=".locopilot/verification-screenshot.png",
    )
    node = make_finalize_node(_deps(db_session))
    result = await node(_state(execution_id, str(tmp_workspace.root), test_results))

    assert result["final_result"]["artifact_count"] == 0
    artifacts = await list_artifacts_for_execution(db_session, execution_id)
    assert artifacts == []


async def test_finalize_handles_no_screenshot_normally(db_session, tmp_workspace: Workspace) -> None:
    execution_id = await _execution_id(db_session, tmp_workspace)
    test_results = TestResult(status="passed", summary="ok")
    node = make_finalize_node(_deps(db_session))
    result = await node(_state(execution_id, str(tmp_workspace.root), test_results))

    assert result["final_result"]["artifact_count"] == 0
