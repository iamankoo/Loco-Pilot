"""Deterministic test doubles for the LLM and tool-calling boundaries.

Only used by tests — production wiring always uses the real
`LangChainStructuredLLMClient` and `BoundToolRunner`. Keeping fakes here
(not in `agents/`) keeps the production path free of test-only code.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from agents.llm_client import ToolCallStep
from tools.execution_result import ToolExecutionResult


class FakeStructuredLLMClient:
    """`responses[ModelName]` may be a single BaseModel/Exception (returned
    every time that model type is requested) or a `list` of them, consumed
    in order — needed for tests where the same agent role is called more
    than once with different expected behavior each time (e.g. a debug
    loop: Developer's first pass should do nothing, its second pass after
    Debugger should apply the real fix).

    `tool_call_scripts` is a queue of *per-call* scripts: each call to
    `generate_with_tools` pops the next inner list and replays exactly
    those `(tool_name, tool_input)` pairs against the real `tool_runner`
    it's given, before returning the final structured result from
    `responses`/`default` — simulating a multi-turn tool-calling LLM
    without needing a real model. Popping one script per call (rather than
    draining one shared queue) is what makes it possible to script, e.g., a
    debug loop where Developer's first turn does nothing, Debugger's turn
    investigates, and Developer's second turn applies the real fix — three
    separate `generate_with_tools` calls, three separate scripts. A test
    with only one such call can pass a single-item list.
    """

    def __init__(
        self,
        responses: dict[str, BaseModel | Exception | list[BaseModel | Exception]] | None = None,
        *,
        default: BaseModel | None = None,
        tool_call_scripts: list[list[tuple[str, dict]]] | None = None,
    ) -> None:
        self._responses = responses or {}
        self._default = default
        self._tool_call_scripts = list(tool_call_scripts or [])
        self.calls: list[tuple[str, str, type]] = []
        self.tool_loop_calls: list[dict] = []

    async def generate(self, *, system: str, user: str, output_model: type) -> Any:
        self.calls.append((system, user, output_model))
        return self._resolve(output_model)

    async def generate_with_tools(
        self,
        *,
        system: str,
        user: str,
        output_model: type,
        tool_runner: Any,
        max_tool_calls: int,
    ) -> tuple[Any, list[ToolCallStep]]:
        self.tool_loop_calls.append({"system": system, "user": user, "output_model": output_model})
        steps: list[ToolCallStep] = []

        script = self._tool_call_scripts.pop(0) if self._tool_call_scripts else []
        for tool_name, tool_input in script[:max_tool_calls]:
            result = await tool_runner.call(tool_name, tool_input)
            steps.append(
                ToolCallStep(
                    tool_name=tool_name,
                    tool_input=tool_input,
                    status=result.status,
                    output=result.output,
                    error=result.error,
                    duration_ms=result.duration_ms,
                )
            )

        final = self._resolve(output_model)
        return final, steps

    def _resolve(self, output_model: type) -> Any:
        key = output_model.__name__
        if key in self._responses:
            value = self._responses[key]
            if isinstance(value, list):
                if not value:
                    raise AssertionError(f"FakeStructuredLLMClient: response queue for {key} exhausted")
                value = value.pop(0)
            if isinstance(value, Exception):
                raise value
            return value
        if self._default is not None:
            return self._default
        raise AssertionError(f"FakeStructuredLLMClient: no response configured for {key}")


class FakeToolRunner:
    """A `ToolRunner` test double with a small in-memory filesystem and
    configurable canned responses, so agent tests don't need a real
    workspace/registry wired up unless they specifically want one."""

    def __init__(
        self,
        *,
        allowed: set[str] | None = None,
        responses: dict[str, ToolExecutionResult] | None = None,
    ) -> None:
        self._allowed = allowed if allowed is not None else set()
        self._responses = responses or {}
        self.calls: list[tuple[str, dict]] = []

    async def call(self, tool_name: str, tool_input: dict) -> ToolExecutionResult:
        self.calls.append((tool_name, tool_input))
        if tool_name not in self._allowed:
            return ToolExecutionResult(
                tool_name=tool_name, status="error", output=None, error="not permitted (fake)", duration_ms=0
            )
        if tool_name in self._responses:
            return self._responses[tool_name]
        return ToolExecutionResult(tool_name=tool_name, status="success", output={}, error=None, duration_ms=0)

    def available_tools(self) -> set[str]:
        return set(self._allowed)

    def tool_schemas(self) -> list[dict]:
        return [
            {"type": "function", "function": {"name": name, "description": "", "parameters": {}}}
            for name in sorted(self._allowed)
        ]
