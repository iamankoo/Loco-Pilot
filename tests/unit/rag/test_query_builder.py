from __future__ import annotations

from agents.schemas import DebugResult, Plan, TestResult
from agents.state import ExecutionState
from rag.retrieval.query_builder import build_retrieval_query


def _state(**overrides) -> ExecutionState:
    defaults = dict(
        execution_id="11111111-1111-1111-1111-111111111111",
        project_id="22222222-2222-2222-2222-222222222222",
        user_task="Fix authentication bug",
        workspace_root="C:/tmp/does-not-matter",
    )
    defaults.update(overrides)
    return ExecutionState(**defaults)


def test_orchestrator_query_extracts_explicit_filename_from_task() -> None:
    query = build_retrieval_query("orchestrator", _state(user_task="Check config.py for a typo"))
    assert query is not None
    assert "config.py" in query.explicit_file_hints


def test_orchestrator_query_falls_back_to_project_context_relevant_files() -> None:
    from analysis.context import ProjectContext
    from analysis.relevant_files import RelevantFile

    state = _state(
        project_context=ProjectContext(
            workspace_root="C:/tmp",
            relevant_files=[RelevantFile(path="auth/auth_service.py", reason="path matches: auth", score=2.0)],
        )
    )
    query = build_retrieval_query("orchestrator", state)
    assert query is not None
    assert "auth/auth_service.py" in query.explicit_file_hints


def test_developer_query_includes_task_plan_and_files_likely_involved() -> None:
    plan = Plan(objective="fix login", steps=["find the bug", "fix it"], testing_strategy="pytest", files_likely_involved=["auth.py"])
    query = build_retrieval_query("developer", _state(plan=plan))
    assert query is not None
    assert "fix login" in query.text
    assert "find the bug" in query.text
    assert "auth.py" in query.explicit_file_hints


def test_developer_query_is_none_without_a_plan() -> None:
    assert build_retrieval_query("developer", _state()) is None


def test_developer_query_includes_debug_result_when_present() -> None:
    plan = Plan(objective="fix login", steps=["a"], testing_strategy="pytest")
    debug_result = DebugResult(
        root_cause="off-by-one error", proposed_fix="use <=", confidence="high", files_to_change=["calc.py"]
    )
    query = build_retrieval_query("developer", _state(plan=plan, debug_result=debug_result))
    assert query is not None
    assert "off-by-one error" in query.text
    assert "calc.py" in query.explicit_file_hints


def test_debugger_query_includes_failure_and_extracts_traceback_file() -> None:
    test_results = TestResult(
        status="failed",
        summary="1 failed",
        errors=['File "auth/jwt.py", line 42, in refresh\n    raise ValueError("expired")'],
    )
    query = build_retrieval_query("debugger", _state(test_results=test_results))
    assert query is not None
    assert "expired" in query.text
    assert "jwt.py" in query.explicit_file_hints


def test_debugger_query_is_none_without_test_results() -> None:
    assert build_retrieval_query("debugger", _state()) is None


def test_query_text_is_bounded() -> None:
    from rag.retrieval.query_builder import MAX_QUERY_CHARS

    plan = Plan(objective="x" * 5000, steps=["a"], testing_strategy="t")
    query = build_retrieval_query("developer", _state(plan=plan))
    assert query is not None
    assert len(query.text) <= MAX_QUERY_CHARS


def test_unknown_stage_returns_none() -> None:
    assert build_retrieval_query("reviewer", _state()) is None
    assert build_retrieval_query("tester", _state()) is None
