from __future__ import annotations

import pytest

from agents.debugger import DebuggerAgent
from agents.llm_client import LLMUnavailableError, ToolCallLimitError
from agents.schemas import DebugResult, TestResult
from agents.state import ExecutionState
from tests.fakes import FakeStructuredLLMClient, FakeToolRunner
from tools.execution_result import ToolExecutionResult


def _state_with_failed_tests() -> ExecutionState:
    return ExecutionState(
        execution_id="11111111-1111-1111-1111-111111111111",
        project_id="22222222-2222-2222-2222-222222222222",
        user_task="fix the bug",
        workspace_root="C:/tmp/does-not-matter",
        test_results=TestResult(status="failed", failed=1, summary="1 test failed", errors=["AssertionError: expected 2, got 1"]),
    )


async def test_debugger_requires_test_results() -> None:
    state = ExecutionState(execution_id="1", project_id="2", user_task="x", workspace_root="C:/tmp")
    agent = DebuggerAgent(llm_client=FakeStructuredLLMClient(), tools=FakeToolRunner(allowed={"read_file"}))
    with pytest.raises(ValueError):
        await agent.run(state)


async def test_debugger_raises_when_llm_unavailable() -> None:
    agent = DebuggerAgent(llm_client=None, tools=FakeToolRunner())
    with pytest.raises(LLMUnavailableError):
        await agent.run(_state_with_failed_tests())


async def test_debugger_increments_retry_count() -> None:
    debug_result = DebugResult(root_cause="off by one", proposed_fix="add 1", confidence="high", files_to_change=["a.py"])
    llm = FakeStructuredLLMClient({"DebugResult": debug_result})
    agent = DebuggerAgent(llm_client=llm, tools=FakeToolRunner(allowed={"read_file"}))

    state = _state_with_failed_tests()
    update = await agent.run(state)

    assert update["retry_count"] == state.retry_count + 1
    assert update["execution_status"] == "developing"
    assert "off by one" in update["messages"][0]


async def test_debugger_never_calls_a_write_tool() -> None:
    debug_result = DebugResult(root_cause="x", proposed_fix="y", confidence="low")
    llm = FakeStructuredLLMClient({"DebugResult": debug_result})
    tools = FakeToolRunner(allowed={"read_file", "write_file", "edit_file"})

    agent = DebuggerAgent(llm_client=llm, tools=tools)
    await agent.run(_state_with_failed_tests())

    called = {name for name, _ in tools.calls}
    assert "write_file" not in called
    assert "edit_file" not in called


async def test_debugger_investigates_via_real_tool_calls() -> None:
    debug_result = DebugResult(
        root_cause="off by one in add()", proposed_fix="add 1", confidence="high", files_to_change=["a.py"]
    )
    llm = FakeStructuredLLMClient(
        {"DebugResult": debug_result},
        tool_call_scripts=[[("read_file", {"path": "a.py"}), ("search_files", {"query": "def add"})]],
    )
    tools = FakeToolRunner(
        allowed={"read_file", "search_files"},
        responses={
            "read_file": ToolExecutionResult(
                tool_name="read_file", status="success", output={"content": "def add(a, b): return a"}, error=None, duration_ms=1
            ),
            "search_files": ToolExecutionResult(
                tool_name="search_files", status="success", output={"matches": []}, error=None, duration_ms=1
            ),
        },
    )

    agent = DebuggerAgent(llm_client=llm, tools=tools)
    update = await agent.run(_state_with_failed_tests())

    called = [name for name, _ in tools.calls]
    assert called == ["read_file", "search_files"]
    assert len(update["tool_calls"]) == 2
    assert "2 investigative tool call(s)" in update["messages"][0]


async def test_debugger_raises_when_tool_budget_exhausted() -> None:
    debug_result = DebugResult(root_cause="x", proposed_fix="y", confidence="low")
    llm = FakeStructuredLLMClient({"DebugResult": debug_result})
    agent = DebuggerAgent(llm_client=llm, tools=FakeToolRunner(allowed={"read_file"}), max_tool_calls=0)
    with pytest.raises(ToolCallLimitError):
        await agent.run(_state_with_failed_tests())
