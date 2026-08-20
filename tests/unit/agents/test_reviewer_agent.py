from __future__ import annotations

import pytest

from agents.llm_client import LLMUnavailableError
from agents.reviewer import ReviewerAgent
from agents.schemas import ReviewResult, TestResult
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


async def test_reviewer_approved_maps_to_passed_status() -> None:
    review = ReviewResult(verdict="approved", summary="good")
    llm = FakeStructuredLLMClient({"ReviewResult": review})
    agent = ReviewerAgent(llm_client=llm, tools=FakeToolRunner(allowed={"git_diff"}))

    update = await agent.run(_state())
    assert update["execution_status"] == "passed"


async def test_reviewer_changes_required_maps_to_failed_status() -> None:
    review = ReviewResult(verdict="changes_required", summary="missing edge case", issues=["no null check"])
    llm = FakeStructuredLLMClient({"ReviewResult": review})
    agent = ReviewerAgent(llm_client=llm, tools=FakeToolRunner(allowed={"git_diff"}))

    update = await agent.run(_state())
    assert update["execution_status"] == "failed"


async def test_reviewer_never_calls_a_write_tool() -> None:
    review = ReviewResult(verdict="approved", summary="good")
    llm = FakeStructuredLLMClient({"ReviewResult": review})
    tools = FakeToolRunner(allowed={"git_diff", "write_file"})

    agent = ReviewerAgent(llm_client=llm, tools=tools)
    await agent.run(_state())

    called = {name for name, _ in tools.calls}
    assert "write_file" not in called
