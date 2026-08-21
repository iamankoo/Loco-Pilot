from __future__ import annotations

import pytest

from agents.developer import DeveloperAgent
from agents.llm_client import LLMUnavailableError, ToolCallLimitError
from agents.schemas import DebugResult, DeveloperPlan, Plan
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
    state = ExecutionState(execution_id="1", project_id="2", user_task="x", workspace_root="C:/tmp")
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


async def test_developer_raises_when_tool_budget_exhausted() -> None:
    plan = Plan(objective="x", steps=["a"], testing_strategy="t")
    agent = DeveloperAgent(
        llm_client=FakeStructuredLLMClient(), tools=FakeToolRunner(allowed={"write_file"}), max_tool_calls=0
    )
    with pytest.raises(ToolCallLimitError):
        await agent.run(_state_with_plan(plan))


async def test_developer_applies_a_successful_write_via_its_own_tool_call() -> None:
    plan = Plan(objective="x", steps=["a"], testing_strategy="t")
    llm = FakeStructuredLLMClient(
        {"DeveloperPlan": DeveloperPlan(summary="added new.py")},
        tool_call_scripts=[[("write_file", {"path": "new.py", "content": "x = 1"})]],
    )
    tools = FakeToolRunner(
        allowed={"read_file", "write_file", "edit_file"},
        responses={
            "write_file": ToolExecutionResult(
                tool_name="write_file",
                status="success",
                output={"path": "new.py", "created": True, "bytes_written": 5},
                error=None,
                duration_ms=1,
            )
        },
    )

    agent = DeveloperAgent(llm_client=llm, tools=tools)
    update = await agent.run(_state_with_plan(plan))

    assert len(update["files_changed"]) == 1
    assert update["files_changed"][0].change_type == "created"
    assert update["files_changed"][0].path == "new.py"
    assert len(update["tool_calls"]) == 1
    assert update["tool_calls"][0].tool_name == "write_file"
    assert ("write_file", {"path": "new.py", "content": "x = 1"}) in tools.calls


async def test_developer_records_failed_edit_honestly() -> None:
    plan = Plan(objective="x", steps=["a"], testing_strategy="t")
    llm = FakeStructuredLLMClient(
        {"DeveloperPlan": DeveloperPlan(summary="attempted edit")},
        tool_call_scripts=[[("edit_file", {"path": "a.py", "old_string": "missing", "new_string": "found"})]],
    )
    tools = FakeToolRunner(
        allowed={"read_file", "write_file", "edit_file"},
        responses={
            "edit_file": ToolExecutionResult(
                tool_name="edit_file",
                status="error",
                output=None,
                error="old_string was not found in the file.",
                duration_ms=1,
            )
        },
    )

    agent = DeveloperAgent(llm_client=llm, tools=tools)
    update = await agent.run(_state_with_plan(plan))

    assert update["files_changed"][0].change_type == "failed"
    assert "not found" in update["files_changed"][0].detail
    assert update["tool_calls"][0].status == "error"


async def test_developer_can_read_before_editing_in_the_same_loop() -> None:
    plan = Plan(objective="x", steps=["a"], testing_strategy="t", files_likely_involved=["existing.py"])
    llm = FakeStructuredLLMClient(
        {"DeveloperPlan": DeveloperPlan(summary="read then edited existing.py")},
        tool_call_scripts=[
            [
                ("read_file", {"path": "existing.py"}),
                ("edit_file", {"path": "existing.py", "old_string": "old = 1", "new_string": "old = 2"}),
            ]
        ],
    )
    tools = FakeToolRunner(
        allowed={"read_file", "write_file", "edit_file"},
        responses={
            "read_file": ToolExecutionResult(
                tool_name="read_file",
                status="success",
                output={"path": "existing.py", "content": "old = 1", "truncated": False, "size_bytes": 7},
                error=None,
                duration_ms=1,
            ),
            "edit_file": ToolExecutionResult(
                tool_name="edit_file",
                status="success",
                output={"path": "existing.py", "replaced": True, "occurrences": 1},
                error=None,
                duration_ms=1,
            ),
        },
    )

    agent = DeveloperAgent(llm_client=llm, tools=tools)
    update = await agent.run(_state_with_plan(plan))

    called_tools = [name for name, _ in tools.calls]
    assert called_tools == ["read_file", "edit_file"]
    assert update["files_changed"][0].change_type == "modified"
    assert len(update["tool_calls"]) == 2


async def test_developer_retry_prompt_uses_the_debugger_finding_when_present() -> None:
    """On a retry where Debugger has already investigated, the retry
    prompt must be built from its structured `DebugResult`, not the crude
    `messages[-5:]` fallback — that fallback is only for the case where no
    structured finding exists yet."""
    plan = Plan(objective="x", steps=["a"], testing_strategy="t")
    debug_result = DebugResult(
        root_cause="off-by-one error", proposed_fix="use <= instead of <", confidence="high", files_to_change=["calc.py"]
    )
    state = ExecutionState(
        execution_id="11111111-1111-1111-1111-111111111111",
        project_id="22222222-2222-2222-2222-222222222222",
        user_task="fix the bug",
        workspace_root="C:/tmp/does-not-matter",
        plan=plan,
        retry_count=1,
        debug_result=debug_result,
        messages=["this stale free-text note must not be what the prompt relies on"],
    )
    llm = FakeStructuredLLMClient({"DeveloperPlan": DeveloperPlan(summary="applied the fix")})
    agent = DeveloperAgent(llm_client=llm, tools=FakeToolRunner(allowed={"read_file", "write_file", "edit_file"}))

    await agent.run(state)

    assert len(llm.tool_loop_calls) == 1
    prompt = llm.tool_loop_calls[0]["user"]
    assert "off-by-one error" in prompt
    assert "use <= instead of <" in prompt
    assert "calc.py" in prompt


async def test_developer_tool_loop_is_bounded_by_max_tool_calls() -> None:
    plan = Plan(objective="x", steps=["a"], testing_strategy="t")
    # Script more calls than the agent is permitted to make.
    script = [("read_file", {"path": f"f{i}.py"}) for i in range(5)]
    llm = FakeStructuredLLMClient({"DeveloperPlan": DeveloperPlan(summary="done")}, tool_call_scripts=[script])
    tools = FakeToolRunner(
        allowed={"read_file"},
        responses={
            "read_file": ToolExecutionResult(
                tool_name="read_file", status="success", output={"content": "x"}, error=None, duration_ms=1
            )
        },
    )

    agent = DeveloperAgent(llm_client=llm, tools=tools, max_tool_calls=2)
    update = await agent.run(_state_with_plan(plan))

    assert len(tools.calls) == 2
    assert len(update["tool_calls"]) == 2


async def test_developer_tracks_a_successful_delete_as_deleted() -> None:
    plan = Plan(objective="x", steps=["a"], testing_strategy="t")
    llm = FakeStructuredLLMClient(
        {"DeveloperPlan": DeveloperPlan(summary="removed the obsolete file")},
        tool_call_scripts=[[("delete_file", {"path": "old.py"})]],
    )
    tools = FakeToolRunner(
        allowed={"read_file", "write_file", "edit_file", "delete_file"},
        responses={
            "delete_file": ToolExecutionResult(
                tool_name="delete_file",
                status="success",
                output={"path": "old.py", "deleted": True, "was_directory": False, "diff": "-old\n", "diff_truncated": False},
                error=None,
                duration_ms=1,
            )
        },
    )

    agent = DeveloperAgent(llm_client=llm, tools=tools)
    update = await agent.run(_state_with_plan(plan))

    assert update["files_changed"][0].path == "old.py"
    assert update["files_changed"][0].change_type == "deleted"


async def test_developer_tracks_a_successful_move_as_renamed() -> None:
    plan = Plan(objective="x", steps=["a"], testing_strategy="t")
    llm = FakeStructuredLLMClient(
        {"DeveloperPlan": DeveloperPlan(summary="renamed the module")},
        tool_call_scripts=[[("move_file", {"source_path": "old_name.py", "destination_path": "new_name.py"})]],
    )
    tools = FakeToolRunner(
        allowed={"read_file", "write_file", "edit_file", "move_file"},
        responses={
            "move_file": ToolExecutionResult(
                tool_name="move_file",
                status="success",
                output={
                    "source_path": "old_name.py", "destination_path": "new_name.py", "moved": True, "was_directory": False
                },
                error=None,
                duration_ms=1,
            )
        },
    )

    agent = DeveloperAgent(llm_client=llm, tools=tools)
    update = await agent.run(_state_with_plan(plan))

    assert update["files_changed"][0].path == "new_name.py"
    assert update["files_changed"][0].change_type == "renamed"
    assert "old_name.py" in update["files_changed"][0].detail


async def test_developer_tracks_a_failed_delete_honestly() -> None:
    plan = Plan(objective="x", steps=["a"], testing_strategy="t")
    llm = FakeStructuredLLMClient(
        {"DeveloperPlan": DeveloperPlan(summary="attempted cleanup")},
        tool_call_scripts=[[("delete_file", {"path": "important.py"})]],
    )
    tools = FakeToolRunner(
        allowed={"read_file", "write_file", "edit_file", "delete_file"},
        responses={
            "delete_file": ToolExecutionResult(
                tool_name="delete_file", status="error", output=None, error="Directory is not empty", duration_ms=1
            )
        },
    )

    agent = DeveloperAgent(llm_client=llm, tools=tools)
    update = await agent.run(_state_with_plan(plan))

    assert update["files_changed"][0].change_type == "failed"
    assert "not empty" in update["files_changed"][0].detail


async def test_developer_prompt_includes_workspace_scans_relevant_files_as_a_hint() -> None:
    """Phase 2.2's ProjectContext.relevant_files must reach Developer's
    prompt — as a hint to investigate, not an instruction to blindly
    modify (the prompt text must make that distinction explicit)."""
    from analysis.context import ProjectContext
    from analysis.relevant_files import RelevantFile

    plan = Plan(objective="x", steps=["a"], testing_strategy="t")
    state = _state_with_plan(plan).model_copy(
        update={
            "project_context": ProjectContext(
                workspace_root="C:/tmp/does-not-matter",
                relevant_files=[RelevantFile(path="backend/app/auth/auth_service.py", reason="path matches: auth", score=2.0)],
            )
        }
    )
    llm = FakeStructuredLLMClient({"DeveloperPlan": DeveloperPlan(summary="done")})
    agent = DeveloperAgent(llm_client=llm, tools=FakeToolRunner(allowed={"read_file", "write_file", "edit_file"}))

    await agent.run(state)

    prompt = llm.tool_loop_calls[0]["user"]
    assert "backend/app/auth/auth_service.py" in prompt
    assert "hint, not an instruction" in prompt
