from __future__ import annotations

import pytest

from agents.llm_client import LLMUnavailableError, MalformedLLMOutputError
from agents.planner import PlannerAgent
from agents.schemas import Plan
from agents.state import ExecutionState
from tests.fakes import FakeStructuredLLMClient, FakeToolRunner


def _state(**overrides) -> ExecutionState:
    defaults = dict(
        execution_id="11111111-1111-1111-1111-111111111111",
        project_id="22222222-2222-2222-2222-222222222222",
        user_task="add input validation",
        workspace_root="C:/tmp/does-not-matter",
    )
    defaults.update(overrides)
    return ExecutionState(**defaults)


async def test_planner_produces_plan_from_fake_llm() -> None:
    plan = Plan(objective="validate input", steps=["add a check"], testing_strategy="unit test")
    llm = FakeStructuredLLMClient({"Plan": plan})
    tools = FakeToolRunner(allowed={"list_directory"})

    agent = PlannerAgent(llm_client=llm, tools=tools)
    update = await agent.run(_state())

    assert update["plan"] == plan
    assert update["execution_status"] == "developing"
    assert any("plan" in m.lower() for m in update["messages"])


async def test_planner_raises_when_llm_unavailable() -> None:
    agent = PlannerAgent(llm_client=None, tools=FakeToolRunner())
    with pytest.raises(LLMUnavailableError):
        await agent.run(_state())


async def test_planner_propagates_malformed_output() -> None:
    llm = FakeStructuredLLMClient({"Plan": MalformedLLMOutputError("bad shape")})
    agent = PlannerAgent(llm_client=llm, tools=FakeToolRunner(allowed={"list_directory"}))
    with pytest.raises(MalformedLLMOutputError):
        await agent.run(_state())


async def test_planner_survives_grounding_tool_failure() -> None:
    """list_directory failing should not prevent planning — it's best-effort grounding."""
    plan = Plan(objective="x", steps=["a"], testing_strategy="unit test")
    llm = FakeStructuredLLMClient({"Plan": plan})
    tools = FakeToolRunner(allowed=set())  # list_directory not permitted -> tool call fails

    agent = PlannerAgent(llm_client=llm, tools=tools)
    update = await agent.run(_state())
    assert update["plan"] == plan


async def test_planner_never_calls_a_write_tool() -> None:
    plan = Plan(objective="x", steps=["a"], testing_strategy="unit test")
    llm = FakeStructuredLLMClient({"Plan": plan})
    tools = FakeToolRunner(allowed={"list_directory", "write_file"})

    agent = PlannerAgent(llm_client=llm, tools=tools)
    await agent.run(_state())

    called_tools = {name for name, _ in tools.calls}
    assert "write_file" not in called_tools
