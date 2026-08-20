"""Deterministic test doubles for the LLM and tool-calling boundaries.

Only used by tests — production wiring always uses the real
`LangChainStructuredLLMClient` and `BoundToolRunner`. Keeping fakes here
(not in `agents/`) keeps the production path free of test-only code.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from tools.execution_result import ToolExecutionResult


class FakeStructuredLLMClient:
    """`responses[ModelName]` may be a single BaseModel/Exception (returned
    every time that model type is requested) or a `list` of them, consumed
    in order — needed for tests where the same agent role is called more
    than once with different expected behavior each time (e.g. a debug
    loop: Developer's first pass should do nothing, its second pass after
    Debugger should apply the real fix)."""

    def __init__(
        self,
        responses: dict[str, BaseModel | Exception | list[BaseModel | Exception]] | None = None,
        *,
        default: BaseModel | None = None,
    ) -> None:
        self._responses = responses or {}
        self._default = default
        self.calls: list[tuple[str, str, type]] = []

    async def generate(self, *, system: str, user: str, output_model: type) -> Any:
        self.calls.append((system, user, output_model))
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
