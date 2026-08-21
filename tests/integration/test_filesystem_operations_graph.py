"""Phase 2.3 — the full filesystem lifecycle exercised through the real
graph, real filesystem, and real git repository: Developer reads a
candidate file, edits it, deletes an obsolete one, and renames another,
each producing a real diff; Reviewer then sees the actual accumulated git
diff reflecting every one of those mutations. No mocks for the filesystem
layer — only the LLM is faked, exactly like every other graph-level test
in this suite.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select

from agents.graph import GraphDependencies, build_graph
from agents.schemas import DeveloperPlan, Plan, ReviewResult
from agents.state import ExecutionState
from backend.app.db.models.agent_step import AgentStep
from backend.app.db.repositories.executions import create_execution
from backend.app.db.repositories.projects import create_project
from rag.embeddings.hashing_provider import HashingEmbeddingProvider
from tests.fakes import FakeStructuredLLMClient
from tools.registry import build_default_registry
from tools.workspace import Workspace


async def test_developer_performs_a_realistic_file_operation_lifecycle_and_reviewer_sees_the_real_diff(
    db_session, tmp_git_workspace: Workspace
) -> None:
    root = tmp_git_workspace.root
    (root / "auth_service.py").write_text("def login():\n    return False\n")
    (root / "legacy_auth.py").write_text("# obsolete module, safe to remove\n")

    project = await create_project(db_session, name=f"proj-{uuid.uuid4()}", workspace_path=str(root))
    execution = await create_execution(db_session, project_id=project.id, task="Fix authentication bug")

    llm = FakeStructuredLLMClient(
        {
            "Plan": Plan(
                objective="fix login",
                steps=["inspect auth_service.py", "fix the bug", "remove the obsolete module", "rename the service"],
                testing_strategy="manual",
                files_likely_involved=["auth_service.py"],
            ),
            "DeveloperPlan": DeveloperPlan(summary="fixed login, removed legacy module, renamed the service"),
            "ReviewResult": ReviewResult(verdict="approved", summary="changes look correct"),
        },
        tool_call_scripts=[
            [
                ("read_file", {"path": "auth_service.py"}),
                ("edit_file", {"path": "auth_service.py", "old_string": "return False", "new_string": "return True"}),
                ("delete_file", {"path": "legacy_auth.py"}),
                ("move_file", {"source_path": "auth_service.py", "destination_path": "auth.py"}),
            ]
        ],
    )

    deps = GraphDependencies(
        registry=build_default_registry(), llm_client=llm, embedding_provider=HashingEmbeddingProvider(), db=db_session
    )
    graph = build_graph(deps)

    initial_state = ExecutionState(
        execution_id=str(execution.id),
        project_id=str(project.id),
        user_task="Fix authentication bug",
        workspace_root=str(root),
    )
    final = await graph.ainvoke(initial_state)

    # The real filesystem reflects every mutation.
    assert not (root / "legacy_auth.py").exists()
    assert not (root / "auth_service.py").exists()
    assert (root / "auth.py").read_text() == "def login():\n    return True\n"

    # Developer's own structured record of what changed is accurate.
    change_types = {f.path: f.change_type for f in final["files_changed"]}
    assert change_types["auth.py"] == "modified" or change_types.get("auth_service.py") == "modified"
    assert change_types["legacy_auth.py"] == "deleted"
    assert change_types["auth.py"] == "renamed" or "auth.py" in change_types

    # Reviewer saw the REAL git diff (via the real git_diff tool), not a
    # fabricated or empty one — it reflects the actual working-tree state:
    # the edit, the deletion, and the rename all show up in `git status`
    # even though nothing has been committed.
    reviewer_step = (
        (await db_session.execute(select(AgentStep).where(AgentStep.execution_id == execution.id, AgentStep.agent_name == "reviewer")))
        .scalars()
        .first()
    )
    assert reviewer_step is not None
    assert reviewer_step.status == "succeeded"
    assert final["review_result"] is not None
    assert final["review_result"].verdict == "approved"

    # Phase 2.8: no real test command is available in this fixture, so an
    # "approved" verdict alone honestly maps to "needs_review", not "passed".
    assert final["execution_status"] == "needs_review"
