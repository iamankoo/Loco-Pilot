"""The structured-output LLM boundary every agent calls through.

`StructuredLLMClient` is the interface agents depend on — never a concrete
LangChain chat model. `LangChainStructuredLLMClient` is the real
implementation, built from the existing provider-agnostic
`backend.app.core.llm` factory (so Qwen3-Coder — hosted or a local
OpenAI-compatible endpoint — remains a config change, not a code change).
Tests inject a fake implementing the same interface, so the whole agent
suite runs deterministically with no live API required.
"""

from __future__ import annotations

from typing import Protocol, TypeVar

from pydantic import BaseModel

from backend.app.core.errors import LocoPilotError

T = TypeVar("T", bound=BaseModel)


class LLMUnavailableError(LocoPilotError):
    def __init__(self, message: str) -> None:
        super().__init__(message, status_code=503, code="llm_unavailable")


class MalformedLLMOutputError(LocoPilotError):
    def __init__(self, message: str) -> None:
        super().__init__(message, status_code=502, code="malformed_llm_output")


class StructuredLLMClient(Protocol):
    async def generate(self, *, system: str, user: str, output_model: type[T]) -> T: ...


class LangChainStructuredLLMClient:
    def __init__(self, chat_model) -> None:
        self._chat_model = chat_model

    async def generate(self, *, system: str, user: str, output_model: type[T]) -> T:
        from langchain_core.messages import HumanMessage, SystemMessage

        structured = self._chat_model.with_structured_output(output_model)
        try:
            result = await structured.ainvoke([SystemMessage(content=system), HumanMessage(content=user)])
        except TimeoutError as exc:
            raise LLMUnavailableError(f"LLM request timed out: {exc}") from exc
        except Exception as exc:  # noqa: BLE001 - any transport/provider failure is "unavailable", not a crash
            raise LLMUnavailableError(f"LLM request failed: {exc}") from exc

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
