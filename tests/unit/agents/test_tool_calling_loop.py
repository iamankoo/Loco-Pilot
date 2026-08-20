"""Tests the real `LangChainStructuredLLMClient.generate_with_tools` loop
directly (not the test-only `FakeStructuredLLMClient` double) — a stub
chat model plays the role of the LLM, so these exercise the actual
production tool-calling/recovery/limit logic used by Developer/Debugger.
"""

from __future__ import annotations

from langchain_core.messages import AIMessage
from pydantic import BaseModel

from agents.llm_client import LangChainStructuredLLMClient
from tests.fakes import FakeToolRunner
from tools.base import ToolPermissionError
from tools.execution_result import ToolExecutionResult


class _FinalResult(BaseModel):
    summary: str


class _StructuredStub:
    def __init__(self, result: BaseModel) -> None:
        self._result = result

    async def ainvoke(self, messages):
        return self._result


class _ToolCallingChatModelStub:
    """Replays a scripted queue of AIMessage responses, one per `ainvoke`."""

    def __init__(self, responses: list[AIMessage], final_result: BaseModel) -> None:
        self._responses = list(responses)
        self._final_structured = _StructuredStub(final_result)
        self.bound_schemas: list[dict] | None = None

    def bind_tools(self, schemas: list[dict]):
        self.bound_schemas = schemas
        return self

    async def ainvoke(self, messages):
        if not self._responses:
            raise AssertionError("stub AIMessage queue exhausted")
        return self._responses.pop(0)

    def with_structured_output(self, output_model):
        return self._final_structured


class _RaisingToolRunner:
    """A `ToolRunner` double that raises instead of returning a result —
    exercises `generate_with_tools`'s except-and-recover path specifically,
    which `FakeToolRunner` (lenient, always returns a result) does not."""

    def __init__(self, exc: Exception) -> None:
        self._exc = exc
        self.calls: list[tuple[str, dict]] = []

    async def call(self, tool_name: str, tool_input: dict):
        self.calls.append((tool_name, tool_input))
        raise self._exc

    def available_tools(self) -> set[str]:
        return set()

    def tool_schemas(self) -> list[dict]:
        return []


def _ai_message_with_tool_call(name: str, args: dict, call_id: str = "call_1") -> AIMessage:
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": call_id}])


_NO_MORE_TOOLS = AIMessage(content="done")


async def test_valid_tool_call_then_final_structured_result() -> None:
    chat_model = _ToolCallingChatModelStub(
        responses=[_ai_message_with_tool_call("read_file", {"path": "a.py"}), _NO_MORE_TOOLS],
        final_result=_FinalResult(summary="done"),
    )
    client = LangChainStructuredLLMClient(chat_model)
    tools = FakeToolRunner(
        allowed={"read_file"},
        responses={
            "read_file": ToolExecutionResult(
                tool_name="read_file", status="success", output={"content": "x"}, error=None, duration_ms=1
            )
        },
    )

    result, steps = await client.generate_with_tools(
        system="sys", user="usr", output_model=_FinalResult, tool_runner=tools, max_tool_calls=10
    )

    assert result.summary == "done"
    assert len(steps) == 1
    assert steps[0].tool_name == "read_file"
    assert steps[0].status == "success"
    assert chat_model.bound_schemas == tools.tool_schemas()


async def test_unauthorized_tool_call_is_recorded_and_model_recovers() -> None:
    chat_model = _ToolCallingChatModelStub(
        responses=[_ai_message_with_tool_call("write_file", {"path": "a.py", "content": "x"}), _NO_MORE_TOOLS],
        final_result=_FinalResult(summary="recovered"),
    )
    client = LangChainStructuredLLMClient(chat_model)
    tools = _RaisingToolRunner(ToolPermissionError("Tool 'write_file' is not permitted for this agent."))

    result, steps = await client.generate_with_tools(
        system="sys", user="usr", output_model=_FinalResult, tool_runner=tools, max_tool_calls=10
    )

    # The loop never crashed — it recorded the rejection and let the model continue.
    assert result.summary == "recovered"
    assert len(steps) == 1
    assert steps[0].status == "error"
    assert "not permitted" in steps[0].error
    assert tools.calls == [("write_file", {"path": "a.py", "content": "x"})]


async def test_malformed_arguments_surface_as_an_error_step_not_a_crash() -> None:
    chat_model = _ToolCallingChatModelStub(
        responses=[_ai_message_with_tool_call("edit_file", {"path": "a.py"}), _NO_MORE_TOOLS],
        final_result=_FinalResult(summary="handled bad args"),
    )
    client = LangChainStructuredLLMClient(chat_model)
    tools = FakeToolRunner(
        allowed={"edit_file"},
        responses={
            "edit_file": ToolExecutionResult(
                tool_name="edit_file",
                status="error",
                output=None,
                error="1 validation error for EditFileInput\nold_string\n  Field required",
                duration_ms=0,
            )
        },
    )

    result, steps = await client.generate_with_tools(
        system="sys", user="usr", output_model=_FinalResult, tool_runner=tools, max_tool_calls=10
    )

    assert result.summary == "handled bad args"
    assert steps[0].status == "error"
    assert "validation error" in steps[0].error


async def test_tool_call_limit_is_enforced_within_a_single_response() -> None:
    """The model requests three tool calls in one turn but is only allowed two."""
    many_calls = AIMessage(
        content="",
        tool_calls=[
            {"name": "read_file", "args": {"path": "a.py"}, "id": "1"},
            {"name": "read_file", "args": {"path": "b.py"}, "id": "2"},
            {"name": "read_file", "args": {"path": "c.py"}, "id": "3"},
        ],
    )
    chat_model = _ToolCallingChatModelStub(responses=[many_calls], final_result=_FinalResult(summary="bounded"))
    client = LangChainStructuredLLMClient(chat_model)
    tools = FakeToolRunner(
        allowed={"read_file"},
        responses={
            "read_file": ToolExecutionResult(
                tool_name="read_file", status="success", output={"content": "x"}, error=None, duration_ms=1
            )
        },
    )

    result, steps = await client.generate_with_tools(
        system="sys", user="usr", output_model=_FinalResult, tool_runner=tools, max_tool_calls=2
    )

    assert result.summary == "bounded"
    assert len(steps) == 2  # the third request never reached the tool runner
    assert len(tools.calls) == 2


async def test_no_tools_available_still_produces_a_final_result() -> None:
    chat_model = _ToolCallingChatModelStub(responses=[_NO_MORE_TOOLS], final_result=_FinalResult(summary="no tools needed"))
    client = LangChainStructuredLLMClient(chat_model)
    tools = FakeToolRunner(allowed=set())

    result, steps = await client.generate_with_tools(
        system="sys", user="usr", output_model=_FinalResult, tool_runner=tools, max_tool_calls=5
    )

    assert result.summary == "no tools needed"
    assert steps == []
    assert chat_model.bound_schemas is None  # bind_tools is skipped entirely when there are no tools to offer
