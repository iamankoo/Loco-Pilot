"""FIXTURE B — feature task: a small existing project where the agent must
add a new function and its test, with no pre-existing bug and no debug
loop needed:

task -> inspect -> plan -> implement -> test -> review -> success

Real Docker/pytest execution at every Tester step; every Developer tool
call is executed by the real tool registry against the real files on
disk. LLM reasoning is scripted (no live key in this environment) — same
disclosed methodology as `test_debug_loop_real_execution.py`.
"""

from __future__ import annotations

import shutil
import uuid
from pathlib import Path

from sqlalchemy import select

from agents.graph import GraphDependencies, build_graph
from agents.schemas import DeveloperPlan, Plan, ReviewResult, TestResult
from agents.state import ExecutionState
from backend.app.db.models.agent_step import AgentStep
from backend.app.db.repositories.executions import create_execution
from backend.app.db.repositories.projects import create_project
from rag.embeddings.hashing_provider import HashingEmbeddingProvider
from tests.fakes import FakeStructuredLLMClient
from tools.registry import build_default_registry
from tools.workspace import Workspace

FIXTURE_ROOT = Path(__file__).resolve().parents[3] / "playground" / "feature-project"

_SHOUT_FN = 'def shout(s):\n    return s.upper() + "!"\n'
_REVERSE_WORDS_FN = '\n\ndef reverse_words(s):\n    return " ".join(reversed(s.split()))\n'

_SHOUT_TEST = 'def test_shout():\n    assert shout("hello") == "HELLO!"\n'
_REVERSE_WORDS_TEST = (
    '\n\ndef test_reverse_words():\n'
    '    from stringutils import reverse_words\n'
    '    assert reverse_words("hello world") == "world hello"\n'
)


async def test_feature_task_end_to_end_add_function_and_test(db_session, tmp_path: Path) -> None:
    workspace_dir = tmp_path / "feature-project"
    shutil.copytree(FIXTURE_ROOT, workspace_dir)
    workspace = Workspace.at(workspace_dir)

    project = await create_project(db_session, name=f"proj-{uuid.uuid4()}", workspace_path=str(workspace.root))
    task = "Add a reverse_words(s) function to stringutils.py that reverses word order in a sentence, with a test."
    execution = await create_execution(db_session, project_id=project.id, task=task)

    llm = FakeStructuredLLMClient(
        {
            "Plan": Plan(
                objective="add reverse_words",
                steps=["implement reverse_words in stringutils.py", "add a test for it"],
                testing_strategy="run pytest",
                files_likely_involved=["stringutils.py", "test_stringutils.py"],
            ),
            "DeveloperPlan": DeveloperPlan(summary="implemented reverse_words and its test"),
            # Tester delegates structured interpretation of the real exit
            # code/output to the LLM whenever one is configured (see
            # agents/tester.py) — this correctly reflects the real pytest
            # run's outcome (2 passed) once the fix above is genuinely applied.
            "TestResult": TestResult(
                status="passed", commands=["python -m pytest"], passed=2, failed=0, summary="2 passed"
            ),
            "ReviewResult": ReviewResult(verdict="approved", summary="feature implemented and covered by a passing test"),
        },
        tool_call_scripts=[
            [
                (
                    "edit_file",
                    {"path": "stringutils.py", "old_string": _SHOUT_FN, "new_string": _SHOUT_FN + _REVERSE_WORDS_FN},
                ),
                (
                    "edit_file",
                    {
                        "path": "test_stringutils.py",
                        "old_string": _SHOUT_TEST,
                        "new_string": _SHOUT_TEST + _REVERSE_WORDS_TEST,
                    },
                ),
            ]
        ],
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
        execution_id=str(execution.id), project_id=str(project.id), user_task=task, workspace_root=str(workspace.root)
    )
    final = await graph.ainvoke(initial_state, config={"recursion_limit": 50})

    assert final["execution_status"] == "passed"
    assert final["retry_count"] == 0  # implemented correctly on the first pass — no debug loop needed
    assert final["test_results"].status == "passed"
    assert final["review_result"].verdict == "approved"

    # Both files were genuinely edited on disk.
    assert "def reverse_words" in (workspace.root / "stringutils.py").read_text()
    assert "def test_reverse_words" in (workspace.root / "test_stringutils.py").read_text()

    steps = (
        (await db_session.execute(select(AgentStep).where(AgentStep.execution_id == execution.id))).scalars().all()
    )
    agent_sequence = [s.agent_name for s in steps]
    assert agent_sequence == ["planner", "developer", "tester", "reviewer"]  # no debugger — passed first try
