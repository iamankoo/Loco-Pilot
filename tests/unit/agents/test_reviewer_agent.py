from __future__ import annotations

import pytest

from agents.llm_client import LLMUnavailableError
from agents.reviewer import ReviewerAgent
from agents.schemas import FileChange, ReviewResult, TestResult
from agents.state import ExecutionState
from tests.fakes import FakeStructuredLLMClient, FakeToolRunner
from tools.execution_result import ToolExecutionResult


def _state() -> ExecutionState:
    return ExecutionState(
        execution_id="11111111-1111-1111-1111-111111111111",
        project_id="22222222-2222-2222-2222-222222222222",
        user_task="add a function",
        workspace_root="C:/tmp/does-not-matter",
        test_results=TestResult(status="unavailable", summary="no execution capability"),
    )


async def test_reviewer_raises_when_llm_unavailable() -> None:
    agent = ReviewerAgent(llm_client=None, tools=FakeToolRunner(allowed={"git_diff"}))
    with pytest.raises(LLMUnavailableError):
        await agent.run(_state())


async def test_reviewer_calls_real_git_diff_tool() -> None:
    review = ReviewResult(verdict="approved", summary="looks good")
    llm = FakeStructuredLLMClient({"ReviewResult": review})
    tools = FakeToolRunner(
        allowed={"git_diff"},
        responses={
            "git_diff": ToolExecutionResult(
                tool_name="git_diff", status="success", output={"diff": "+added_line", "truncated": False}, error=None, duration_ms=5
            )
        },
    )

    agent = ReviewerAgent(llm_client=llm, tools=tools)
    await agent.run(_state())

    assert ("git_diff", {}) in tools.calls
    _, user_prompt, _ = llm.calls[0]
    assert "+added_line" in user_prompt


async def test_reviewer_approved_with_passing_tests_maps_to_passed_status() -> None:
    review = ReviewResult(verdict="approved", summary="good")
    llm = FakeStructuredLLMClient({"ReviewResult": review})
    agent = ReviewerAgent(llm_client=llm, tools=FakeToolRunner(allowed={"git_diff"}))

    state = _state().model_copy(update={"test_results": TestResult(status="passed", summary="3 passed")})
    update = await agent.run(state)
    assert update["execution_status"] == "passed"


async def test_reviewer_approved_without_passing_tests_does_not_report_passed() -> None:
    """Phase 2.8: an "approved" verdict alone is never sufficient — the
    default `_state()` fixture's test_results.status is "unavailable"."""
    review = ReviewResult(verdict="approved", summary="good")
    llm = FakeStructuredLLMClient({"ReviewResult": review})
    agent = ReviewerAgent(llm_client=llm, tools=FakeToolRunner(allowed={"git_diff"}))

    update = await agent.run(_state())
    assert update["execution_status"] == "needs_review"
    assert update["execution_status"] != "passed"


async def test_reviewer_changes_required_routes_back_to_developer() -> None:
    review = ReviewResult(verdict="changes_required", summary="missing edge case", issues=["no null check"])
    llm = FakeStructuredLLMClient({"ReviewResult": review})
    agent = ReviewerAgent(llm_client=llm, tools=FakeToolRunner(allowed={"git_diff"}))

    update = await agent.run(_state())
    assert update["execution_status"] == "developing"
    assert update["review_retry_count"] == 1
    assert update["review_result"] in update["review_attempts"]


async def test_reviewer_computes_files_reviewed_and_tests_evaluated_deterministically() -> None:
    review = ReviewResult(verdict="approved", summary="good")
    llm = FakeStructuredLLMClient({"ReviewResult": review})
    agent = ReviewerAgent(llm_client=llm, tools=FakeToolRunner(allowed={"git_diff"}))

    state = _state().model_copy(
        update={
            "test_results": TestResult(status="passed", summary="ok", passed=3, failed=1, skipped=2),
            "files_changed": [
                FileChange(path="a.py", change_type="modified", detail="x"),
                FileChange(path="b.py", change_type="created", detail="x"),
                FileChange(path="c.py", change_type="failed", detail="x"),
            ],
        }
    )
    update = await agent.run(state)

    assert update["review_result"].files_reviewed == 2  # the failed tool call isn't a real change
    assert update["review_result"].tests_evaluated == 6  # 3 + 1 + 2


async def test_reviewer_risk_never_reads_calmer_than_the_deterministic_floor() -> None:
    """The LLM under-calls risk ("low") despite listing a security issue —
    the deterministic floor must win."""
    review = ReviewResult(verdict="changes_required", summary="bad", security_issues=["hardcoded secret"], risk="low")
    llm = FakeStructuredLLMClient({"ReviewResult": review})
    agent = ReviewerAgent(llm_client=llm, tools=FakeToolRunner(allowed={"git_diff"}))

    update = await agent.run(_state())
    assert update["review_result"].risk == "high"


async def test_reviewer_risk_is_not_lowered_when_llm_reports_higher_than_the_floor() -> None:
    """The deterministic floor is a floor, not a ceiling — a genuinely
    higher LLM-assessed risk is preserved even with no deterministic signal."""
    review = ReviewResult(verdict="changes_required", summary="bad", risk="high")
    llm = FakeStructuredLLMClient({"ReviewResult": review})
    agent = ReviewerAgent(llm_client=llm, tools=FakeToolRunner(allowed={"git_diff"}))

    update = await agent.run(_state())
    assert update["review_result"].risk == "high"


async def test_reviewer_does_not_escalate_risk_for_a_necessary_unplanned_supporting_file() -> None:
    """A file Planner didn't predict (e.g. server.py, needed to actually
    run a static site it did plan for) must never alone push risk up —
    only a genuinely suspicious unplanned file (see the next test) does."""
    review = ReviewResult(verdict="approved", summary="looks good", risk="low")
    llm = FakeStructuredLLMClient({"ReviewResult": review})
    tools = FakeToolRunner(allowed={"git_diff", "read_file"})

    state = _state().model_copy(
        update={
            "test_results": TestResult(status="passed", summary="ok"),
            "plan": None,
            "files_changed": [
                FileChange(path="index.html", change_type="created", detail="write_file applied"),
                FileChange(path="server.py", change_type="created", detail="write_file applied"),
            ],
        }
    )
    from agents.schemas import Plan

    state = state.model_copy(
        update={"plan": Plan(objective="x", steps=["x"], testing_strategy="x", files_likely_involved=["index.html"])}
    )

    update = await agent_run_with_unexpected_files(llm, tools, state)
    assert update["review_result"].risk == "low"
    assert update["execution_status"] == "passed"


async def test_reviewer_escalates_risk_for_a_genuinely_suspicious_unplanned_file() -> None:
    review = ReviewResult(verdict="approved", summary="looks fine", risk="low")
    llm = FakeStructuredLLMClient({"ReviewResult": review})
    tools = FakeToolRunner(allowed={"git_diff", "read_file"})

    from agents.schemas import Plan

    state = _state().model_copy(
        update={
            "test_results": TestResult(status="passed", summary="ok"),
            "plan": Plan(objective="x", steps=["x"], testing_strategy="x", files_likely_involved=["index.html"]),
            "files_changed": [
                FileChange(path="index.html", change_type="created", detail="write_file applied"),
                FileChange(path=".env", change_type="created", detail="write_file applied"),
            ],
        }
    )

    update = await agent_run_with_unexpected_files(llm, tools, state)
    assert update["review_result"].risk == "high"


async def agent_run_with_unexpected_files(llm, tools, state) -> dict:
    agent = ReviewerAgent(llm_client=llm, tools=tools)
    return await agent.run(state)


async def test_reviewer_reads_actual_file_contents_when_git_diff_unavailable() -> None:
    """Requirement: absence of a Git repository must never make an
    otherwise reviewable generated project impossible to review — Reviewer
    reads the real files directly instead."""
    review = ReviewResult(verdict="approved", summary="ok")
    llm = FakeStructuredLLMClient({"ReviewResult": review})
    tools = FakeToolRunner(
        allowed={"git_diff", "read_file"},
        responses={
            "git_diff": ToolExecutionResult(
                tool_name="git_diff", status="error", output=None,
                error="Workspace is not a Git repository: /tmp/x", error_code="NOT_A_GIT_REPOSITORY", duration_ms=1,
            ),
            "read_file": ToolExecutionResult(
                tool_name="read_file", status="success",
                output={"content": "<html><body>Real Cartoon Site</body></html>", "truncated": False},
                error=None, duration_ms=1,
            ),
        },
    )

    state = _state().model_copy(
        update={"files_changed": [FileChange(path="index.html", change_type="created", detail="write_file applied")]}
    )
    agent = ReviewerAgent(llm_client=llm, tools=tools)
    await agent.run(state)

    assert ("read_file", {"path": "index.html", "max_bytes": 4000}) in tools.calls
    _, user_prompt, _ = llm.calls[0]
    assert "Real Cartoon Site" in user_prompt
    assert "not a Git repository" in user_prompt.lower() or "workspace is not a git repository" in user_prompt.lower()


async def test_reviewer_never_calls_a_write_tool() -> None:
    review = ReviewResult(verdict="approved", summary="good")
    llm = FakeStructuredLLMClient({"ReviewResult": review})
    tools = FakeToolRunner(allowed={"git_diff", "write_file"})

    agent = ReviewerAgent(llm_client=llm, tools=tools)
    await agent.run(_state())

    called = {name for name, _ in tools.calls}
    assert "write_file" not in called
