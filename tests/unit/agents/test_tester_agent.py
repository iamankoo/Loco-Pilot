from __future__ import annotations

from agents.schemas import TestResult
from agents.state import ExecutionState
from agents.tester import TesterAgent
from tests.fakes import FakeStructuredLLMClient, FakeToolRunner
from tools.execution_result import ToolExecutionResult


def _state() -> ExecutionState:
    return ExecutionState(
        execution_id="11111111-1111-1111-1111-111111111111",
        project_id="22222222-2222-2222-2222-222222222222",
        user_task="add a function",
        workspace_root="C:/tmp/does-not-matter",
    )


async def test_tester_reports_unavailable_when_no_execute_tool_and_makes_no_llm_call() -> None:
    """The current, real-world case: no execute-capable tool is registered."""
    llm = FakeStructuredLLMClient()  # would raise AssertionError if called with no configured response
    tools = FakeToolRunner(allowed={"read_file", "search_files"})  # no run_tests / execute_terminal_command

    agent = TesterAgent(llm_client=llm, tools=tools)
    update = await agent.run(_state())

    assert update["test_results"].status == "unavailable"
    assert update["test_results"].passed == 0
    assert update["test_results"].failed == 0
    assert llm.calls == []  # never fabricated an LLM-based verdict


async def test_tester_never_claims_passed_without_execution() -> None:
    tools = FakeToolRunner(allowed={"read_file"})
    agent = TesterAgent(llm_client=None, tools=tools)
    update = await agent.run(_state())
    assert update["test_results"].status != "passed"


async def test_tester_uses_execute_tool_when_available_and_llm_configured() -> None:
    """Future-readiness path: exercised here via a fake execute-capable tool,
    since no real one exists in the Phase 1.3 registry."""
    test_result = TestResult(status="passed", commands=["pytest"], passed=3, failed=0, summary="3 passed")
    llm = FakeStructuredLLMClient({"TestResult": test_result})
    tools = FakeToolRunner(
        allowed={"read_file", "run_tests"},
        responses={
            "run_tests": ToolExecutionResult(
                tool_name="run_tests", status="success", output={"raw": "3 passed in 0.4s"}, error=None, duration_ms=400
            )
        },
    )

    agent = TesterAgent(llm_client=llm, tools=tools)
    update = await agent.run(_state())

    assert update["test_results"] == test_result
    assert len(llm.calls) == 1


async def test_tester_falls_back_deterministically_without_llm_when_execute_tool_available() -> None:
    tools = FakeToolRunner(
        allowed={"run_tests"},
        responses={
            "run_tests": ToolExecutionResult(
                tool_name="run_tests", status="error", output=None, error="pytest exited 1", duration_ms=200
            )
        },
    )
    agent = TesterAgent(llm_client=None, tools=tools)
    update = await agent.run(_state())

    assert update["test_results"].status == "error"
    assert "pytest exited 1" in update["test_results"].errors
