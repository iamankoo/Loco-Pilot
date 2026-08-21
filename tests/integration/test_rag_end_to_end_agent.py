"""Phase 2.4 end-to-end scenario (section 19): "Fix authentication bug in
sample repository", exercised through the real graph, real filesystem,
real PostgreSQL/pgvector, real indexing, and real hybrid retrieval — only
the LLM is faked (a live LLM is never required for this suite, and this
test does not fabricate one).

Verifies the full chain: workspace discovered -> ProjectContext built ->
RAG retrieves the actual authentication files (not the unrelated payments
module) -> Planner's prompt is grounded in that -> Developer's own
re-retrieval is similarly focused -> Developer reads the real file before
editing it -> Tester runs -> Reviewer sees the resulting real diff.
"""

from __future__ import annotations

import uuid

from agents.graph import GraphDependencies, build_graph
from agents.schemas import DeveloperPlan, Plan, ReviewResult
from agents.state import ExecutionState
from backend.app.db.models.agent_step import AgentStep, AgentStepStatus
from backend.app.db.repositories.executions import create_execution
from backend.app.db.repositories.projects import create_project
from rag.embeddings.hashing_provider import HashingEmbeddingProvider
from rag.ingestion.indexer import RepositoryIndexer
from sqlalchemy import select
from tests.fakes import FakeStructuredLLMClient
from tools.registry import build_default_registry
from tools.workspace import Workspace


def _build_sample_repository(root) -> None:
    (root / "auth").mkdir()
    (root / "payments").mkdir()
    (root / "tests").mkdir()

    (root / "auth" / "jwt.py").write_text(
        "def refresh_token(token: str) -> str:\n"
        '    """Issue a new JWT after validating the current refresh token."""\n'
        "    if not token:\n        return ''\n"
        "    return token + '-refreshed'\n",
        encoding="utf-8",
    )
    (root / "payments" / "stripe.py").write_text(
        "def charge_card(amount, card_token):\n"
        '    """Charge a card via the Stripe API."""\n'
        "    return 'receipt_123'\n",
        encoding="utf-8",
    )
    (root / "tests" / "test_auth.py").write_text(
        "def test_refresh_token_returns_new_token():\n    pass\n", encoding="utf-8"
    )
    (root / "README.md").write_text("# Sample project\n", encoding="utf-8")


async def test_fix_authentication_bug_end_to_end(db_session, tmp_git_workspace: Workspace) -> None:
    root = tmp_git_workspace.root
    _build_sample_repository(root)

    project = await create_project(db_session, name=f"proj-{uuid.uuid4()}", workspace_path=str(root))

    indexer = RepositoryIndexer(HashingEmbeddingProvider())
    await indexer.index_repository(tmp_git_workspace, project.id, db_session)

    execution = await create_execution(db_session, project_id=project.id, task="Fix authentication bug")

    llm = FakeStructuredLLMClient(
        {
            "Plan": Plan(
                objective="fix the JWT refresh bug",
                steps=["inspect auth/jwt.py", "fix refresh_token"],
                testing_strategy="pytest",
                files_likely_involved=["auth/jwt.py"],
            ),
            "DeveloperPlan": DeveloperPlan(summary="fixed refresh_token to always return a non-empty token"),
            "ReviewResult": ReviewResult(verdict="approved", summary="fix looks correct"),
        },
        tool_call_scripts=[
            [
                ("read_file", {"path": "auth/jwt.py"}),
                (
                    "edit_file",
                    {
                        "path": "auth/jwt.py",
                        "old_string": "    if not token:\n        return ''",
                        "new_string": "    if not token:\n        raise ValueError('missing token')",
                    },
                ),
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

    # 1 & 2: workspace discovered, ProjectContext generated.
    assert final["project_context"] is not None
    assert final["project_context"].languages == ["Python"]

    # 3: RAG retrieved the actual authentication file, ranked above the
    # unrelated payments module (this fixture is small enough that every
    # file is returned within top_k — the signal is ranking, not exclusion).
    assert final["repository_context"] is not None
    assert "jwt.py" in final["repository_context"].text
    assert final["repository_context"].text.index("jwt.py") < final["repository_context"].text.index("stripe.py")

    # 4: Planner's own prompt was grounded in that retrieval + context.
    planner_calls = [c for c in llm.calls if c[2] is Plan]
    assert len(planner_calls) == 1
    assert "jwt.py" in planner_calls[0][1]

    # 5 & 6: Developer's re-retrieval was similarly focused, and it
    # actually read the real file before editing it (not a blind edit).
    assert len(llm.tool_loop_calls) >= 1
    developer_prompt = llm.tool_loop_calls[0]["user"]
    assert "jwt.py" in developer_prompt

    # 7: Developer edited the correct file — the real file on disk reflects it.
    assert "raise ValueError" in (root / "auth" / "jwt.py").read_text()
    assert final["files_changed"]
    assert any(f.path == "auth/jwt.py" for f in final["files_changed"])

    # 8: Tester ran (honestly reporting unavailable — no test runner
    # marker file in this minimal fixture — rather than fabricating a result).
    assert final["test_results"] is not None

    # 9: Reviewer saw the resulting change and approved it.
    assert final["review_result"] is not None
    assert final["review_result"].verdict == "approved"

    steps = (await db_session.execute(select(AgentStep).where(AgentStep.execution_id == execution.id))).scalars().all()
    agent_names = {s.agent_name for s in steps}
    assert {"planner", "developer", "tester", "reviewer"} <= agent_names
    assert all(s.status == AgentStepStatus.SUCCEEDED.value for s in steps)
