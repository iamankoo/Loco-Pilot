from __future__ import annotations

import pytest

from agents.developer import DeveloperAgent
from agents.llm_client import LLMUnavailableError
from agents.schemas import DeveloperPlan, Plan, ProposedEdit, ProposedWrite
from agents.state import ExecutionState
from tests.fakes import FakeStructuredLLMClient, FakeToolRunner
from tools.execution_result import ToolExecutionResult


def _state_with_plan(plan: Plan) -> ExecutionState:
    return ExecutionState(
        execution_id="11111111-1111-1111-1111-111111111111",
        project_id="22222222-2222-2222-2222-222222222222",
        user_task="add a function",
        workspace_root="C:/tmp/does-not-matter",
        plan=plan,
    )


async def test_developer_requires_a_plan() -> None:
    state = ExecutionState(
        execution_id="1", project_id="2", user_task="x", workspace_root="C:/tmp"
    )
    agent = DeveloperAgent(
        llm_client=FakeStructuredLLMClient(), tools=FakeToolRunner(allowed={"read_file", "write_file", "edit_file"})
    )
    with pytest.raises(ValueError):
        await agent.run(state)


async def test_developer_raises_when_llm_unavailable() -> None:
    plan = Plan(objective="x", steps=["a"], testing_strategy="t")
    agent = DeveloperAgent(llm_client=None, tools=FakeToolRunner())
    with pytest.raises(LLMUnavailableError):
        await agent.run(_state_with_plan(plan))


async def test_developer_applies_successful_write() -> None:
    plan = Plan(objective="x", steps=["a"], testing_strategy="t", files_likely_involved=[])
    dev_plan = DeveloperPlan(summary="added file", writes=[ProposedWrite(path="new.py", content="x = 1")])
    llm = FakeStructuredLLMClient({"DeveloperPlan": dev_plan})
    tools = FakeToolRunner(
        allowed={"read_file", "write_file", "edit_file"},
        responses={
            "write_file": ToolExecutionResult(
                tool_name="write_file", status="success", output={"path": "new.py", "created": True, "bytes_written": 5}, error=None, duration_ms=1
            )
        },
    )

    agent = DeveloperAgent(llm_client=llm, tools=tools)
    update = await agent.run(_state_with_plan(plan))

    assert len(update["files_changed"]) == 1
    assert update["files_changed"][0].change_type == "created"
    assert update["files_changed"][0].path == "new.py"


async def test_developer_records_failed_edit_honestly() -> None:
    plan = Plan(objective="x", steps=["a"], testing_strategy="t")
    dev_plan = DeveloperPlan(
        summary="attempted edit", edits=[ProposedEdit(path="a.py", old_string="missing", new_string="found")]
    )
    llm = FakeStructuredLLMClient({"DeveloperPlan": dev_plan})
    tools = FakeToolRunner(
        allowed={"read_file", "write_file", "edit_file"},
        responses={
            "edit_file": ToolExecutionResult(
                tool_name="edit_file", status="error", output=None, error="old_string was not found in the file.", duration_ms=1
            )
        },
    )

    agent = DeveloperAgent(llm_client=llm, tools=tools)
    update = await agent.run(_state_with_plan(plan))

    assert update["files_changed"][0].change_type == "failed"
    assert "not found" in update["files_changed"][0].detail


async def test_developer_prefetches_files_from_plan() -> None:
    plan = Plan(objective="x", steps=["a"], testing_strategy="t", files_likely_involved=["existing.py"])
    dev_plan = DeveloperPlan(summary="no-op")
    llm = FakeStructuredLLMClient({"DeveloperPlan": dev_plan})
    tools = FakeToolRunner(
        allowed={"read_file", "write_file", "edit_file"},
        responses={
            "read_file": ToolExecutionResult(
                tool_name="read_file", status="success", output={"path": "existing.py", "content": "old = 1", "truncated": False, "size_bytes": 7}, error=None, duration_ms=1
            )
        },
    )

    agent = DeveloperAgent(llm_client=llm, tools=tools)
    await agent.run(_state_with_plan(plan))

    read_calls = [inp for name, inp in tools.calls if name == "read_file"]
    assert {"path": "existing.py"} in read_calls

    # The freshly-read content must actually reach the LLM prompt.
    _, user_prompt, _ = llm.calls[0]
    assert "old = 1" in user_prompt
