"""The structured-output and tool-calling LLM boundary every agent calls through.

`StructuredLLMClient` is the interface agents depend on — never a concrete
LangChain chat model. `LangChainStructuredLLMClient` is the real
implementation, built from the existing provider-agnostic
`backend.app.core.llm` factory (so Qwen3-Coder — hosted or a local
OpenAI-compatible endpoint — remains a config change, not a code change).
Tests inject a fake implementing the same interface, so the whole agent
suite runs deterministically with no live API required.

`generate_with_tools` is the tool-calling loop: the LLM decides which
registry tool to call (if any), each call is executed through the
caller-supplied `ToolRunner` (permission-checked exactly like every other
tool invocation), and the loop repeats — bounded by `max_tool_calls` —
until the LLM stops requesting tools, at which point one final
`with_structured_output` call extracts the structured result from the
full conversation. An unauthorized or unknown tool name is never silently
dropped: the resulting error is fed back to the LLM as a tool result, so
it can recover (e.g. by asking for a permitted tool instead) within the
same bounded loop.

Every individual LLM call goes through `_invoke_with_retries`: some
providers (observed with NVIDIA's hosted Nemotron Ultra) intermittently
return a transient 500/502/503/504/429 or a bare request timeout even for
a well-formed request, and failing the whole multi-turn tool-calling loop
over one such blip would throw away real progress (prior successful tool
calls) for a problem a short retry often resolves. This is a small, bounded
retry (`_MAX_LLM_ATTEMPTS` total attempts, fixed backoff) scoped to
exceptions that are actually transient — never applied to a genuine
auth/validation/model error, which still fails immediately.
"""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING, Protocol, TypeVar

import openai
from pydantic import BaseModel

from backend.app.core.errors import LocoPilotError

if TYPE_CHECKING:
    from agents.base import ToolRunner

T = TypeVar("T", bound=BaseModel)

_MAX_LLM_ATTEMPTS = 3
_RETRY_BACKOFF_SECONDS = 2.0
_RETRYABLE_STATUS_CODES = {408, 429, 500, 502, 503, 504}


def _is_retryable(exc: Exception) -> bool:
    if isinstance(exc, (openai.APITimeoutError, openai.APIConnectionError)):
        return True
    if isinstance(exc, openai.APIStatusError):
        if exc.status_code in _RETRYABLE_STATUS_CODES:
            return True
        # An empty-body 404 (no JSON error explanation, unlike a genuine
        # "model not found") was observed directly against NVIDIA's hosted
        # Nemotron Ultra for a model confirmed present in /v1/models — a
        # routing-layer "no warm replica available" blip, not a permanent
        # not-found. A real "unknown model" 404 always carries an error body.
        if exc.status_code == 404 and not (exc.response.text or "").strip():
            return True
    return False


async def _invoke_with_retries(call):
    """Run `call()` (a zero-arg async callable), retrying a bounded number
    of times only for exceptions classified as transient by `_is_retryable`."""
    last_exc: Exception | None = None
    for attempt in range(_MAX_LLM_ATTEMPTS):
        try:
            return await call()
        except Exception as exc:  # noqa: BLE001 - re-raised verbatim once retries are exhausted
            last_exc = exc
            if attempt == _MAX_LLM_ATTEMPTS - 1 or not _is_retryable(exc):
                raise
            await asyncio.sleep(_RETRY_BACKOFF_SECONDS * (attempt + 1))
    raise last_exc  # pragma: no cover - unreachable, loop always returns or raises


class LLMUnavailableError(LocoPilotError):
    def __init__(self, message: str) -> None:
        super().__init__(message, status_code=503, code="llm_unavailable")


class MalformedLLMOutputError(LocoPilotError):
    def __init__(self, message: str) -> None:
        super().__init__(message, status_code=502, code="malformed_llm_output")


class ToolCallLimitError(LocoPilotError):
    def __init__(self, message: str) -> None:
        super().__init__(message, status_code=429, code="tool_call_limit_exceeded")


class ToolCallStep(BaseModel):
    """One real tool call made during a `generate_with_tools` loop."""

    tool_name: str
    tool_input: dict
    status: str
    output: dict | None = None
    error: str | None = None
    duration_ms: int = 0


class StructuredLLMClient(Protocol):
    async def generate(self, *, system: str, user: str, output_model: type[T]) -> T: ...

    async def generate_with_tools(
        self,
        *,
        system: str,
        user: str,
        output_model: type[T],
        tool_runner: "ToolRunner",
        max_tool_calls: int,
    ) -> tuple[T, list[ToolCallStep]]: ...


class UnavailableLLMClient:
    """A `StructuredLLMClient` that always fails with a specific, known
    reason (e.g. the real provider misconfiguration message) instead of
    a generic "no client configured" error. Used so a Qwen setup problem
    discovered when building the client for a real execution — missing
    key, wrong model, account not authorized, etc. — surfaces to the
    user verbatim rather than being collapsed into one generic message."""

    def __init__(self, reason: str) -> None:
        self._reason = reason

    async def generate(self, *, system: str, user: str, output_model: type[T]) -> T:
        raise LLMUnavailableError(self._reason)

    async def generate_with_tools(
        self,
        *,
        system: str,
        user: str,
        output_model: type[T],
        tool_runner: "ToolRunner",
        max_tool_calls: int,
    ) -> tuple[T, list[ToolCallStep]]:
        raise LLMUnavailableError(self._reason)


class LangChainStructuredLLMClient:
    def __init__(self, chat_model) -> None:
        self._chat_model = chat_model

    async def generate(self, *, system: str, user: str, output_model: type[T]) -> T:
        from langchain_core.messages import HumanMessage, SystemMessage

        structured = self._chat_model.with_structured_output(output_model)
        messages = [SystemMessage(content=system), HumanMessage(content=user)]
        try:
            result = await _invoke_with_retries(lambda: structured.ainvoke(messages))
        except TimeoutError as exc:
            raise LLMUnavailableError(f"LLM request timed out: {exc}") from exc
        except Exception as exc:  # noqa: BLE001 - any transport/provider failure is "unavailable", not a crash
            raise LLMUnavailableError(f"LLM request failed: {exc}") from exc

        return self._coerce(result, output_model)

    async def generate_with_tools(
        self,
        *,
        system: str,
        user: str,
        output_model: type[T],
        tool_runner: "ToolRunner",
        max_tool_calls: int,
    ) -> tuple[T, list[ToolCallStep]]:
        from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

        from tools.base import ToolPermissionError
        from tools.registry import ToolNotFoundError

        schemas = tool_runner.tool_schemas()
        bound_model = self._chat_model.bind_tools(schemas) if schemas else self._chat_model

        messages: list = [SystemMessage(content=system), HumanMessage(content=user)]
        steps: list[ToolCallStep] = []
        calls_made = 0

        while calls_made < max_tool_calls:
            try:
                response: AIMessage = await _invoke_with_retries(lambda: bound_model.ainvoke(messages))
            except Exception as exc:  # noqa: BLE001
                raise LLMUnavailableError(f"LLM request failed: {exc}") from exc
            messages.append(response)

            tool_calls = getattr(response, "tool_calls", None) or []
            if not tool_calls:
                break

            for call in tool_calls:
                tool_name = call.get("name", "")
                tool_input = call.get("args", {}) or {}
                call_id = call.get("id") or tool_name

                if calls_made >= max_tool_calls:
                    messages.append(
                        ToolMessage(
                            content=json.dumps({"error": "tool call limit reached for this turn"}),
                            tool_call_id=call_id,
                        )
                    )
                    continue
                calls_made += 1

                try:
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
                    content = json.dumps({"status": result.status, "output": result.output, "error": result.error})
                except (ToolPermissionError, ToolNotFoundError) as exc:
                    steps.append(
                        ToolCallStep(tool_name=tool_name, tool_input=tool_input, status="error", error=str(exc))
                    )
                    content = json.dumps({"status": "error", "error": str(exc)})

                messages.append(ToolMessage(content=content, tool_call_id=call_id))

        messages.append(
            HumanMessage(content="Based on everything above, provide your final structured result now.")
        )
        structured = self._chat_model.with_structured_output(output_model)
        try:
            final = await _invoke_with_retries(lambda: structured.ainvoke(messages))
        except Exception as exc:  # noqa: BLE001
            raise LLMUnavailableError(f"LLM final structured request failed: {exc}") from exc

        return self._coerce(final, output_model), steps

    def _coerce(self, result: object, output_model: type[T]) -> T:
        if isinstance(result, output_model):
            return result
        try:
            return output_model.model_validate(result)
        except Exception as exc:  # noqa: BLE001
            raise MalformedLLMOutputError(
                f"LLM returned output that doesn't match {output_model.__name__}: {exc}"
            ) from exc


def build_default_llm_client() -> StructuredLLMClient:
    from backend.app.core.llm.factory import get_llm_provider

    return LangChainStructuredLLMClient(get_llm_provider().chat_model())
