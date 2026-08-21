"""Live validation of whichever LLM provider is actually configured
(LLM_PROVIDER — gemini by default, qwen also supported) — clearly
separated from the deterministic suite (per Phase 1.5's requirement),
skip-gated on real credentials.

Every test here either genuinely calls the configured provider or skips
with an explicit reason — never a scripted/fake stand-in, and never
marked passed without a real call actually succeeding. When no API key is
configured, all of these skip and the rest of the suite (which never
depends on them) still runs and passes.
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from agents.llm_client import build_default_llm_client
from agents.schemas import Plan
from backend.app.core.config import get_settings
from backend.app.core.llm.factory import get_llm_provider


def _require_live_credentials() -> None:
    settings = get_settings()
    if not settings.llm_api_key:
        pytest.skip("LLM_API_KEY not configured; skipping live LLM validation.")
    # LLM_BASE_URL only applies to OpenAI-compatible providers (e.g. qwen) —
    # Gemini talks to Google's own endpoint and needs no base URL.
    if settings.llm_provider != "gemini" and not settings.llm_base_url:
        pytest.skip("LLM_BASE_URL not configured; skipping live LLM validation.")


async def test_llm_raw_connectivity() -> None:
    """The configured endpoint responds to a basic chat request at all."""
    _require_live_credentials()
    chat_model = get_llm_provider().chat_model()

    response = await chat_model.ainvoke("Reply with exactly one word: ok")
    assert response.content
    assert len(str(response.content)) < 200


class _Verdict(BaseModel):
    answer: str
    confidence: str


async def test_llm_produces_valid_structured_output() -> None:
    """`with_structured_output` returns a real, schema-valid instance from
    the live model — not just raw unstructured text."""
    _require_live_credentials()
    chat_model = get_llm_provider().chat_model()
    structured = chat_model.with_structured_output(_Verdict)

    result = await structured.ainvoke("Is 2 + 2 equal to 4? Answer 'yes' or 'no' with your confidence.")
    assert isinstance(result, _Verdict)
    assert result.answer


async def test_llm_tool_calling_behavior() -> None:
    """The live model can be offered a tool and produces a well-formed
    tool_calls request when it decides to use it."""
    _require_live_credentials()
    chat_model = get_llm_provider().chat_model()
    schema = {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "Get the current weather for a city.",
            "parameters": {
                "type": "object",
                "properties": {"city": {"type": "string"}},
                "required": ["city"],
            },
        },
    }
    bound = chat_model.bind_tools([schema])

    response = await bound.ainvoke("What is the weather like in Paris right now? Use the available tool.")
    tool_calls = getattr(response, "tool_calls", None) or []
    assert len(tool_calls) >= 1
    assert tool_calls[0]["name"] == "get_weather"
    assert "city" in tool_calls[0]["args"]


async def test_llm_understands_provided_repository_context() -> None:
    """Given a small snippet of retrieved repository context, the model's
    structured answer is actually grounded in it (not merely well-formed)."""
    _require_live_credentials()

    class _FunctionAnswer(BaseModel):
        function_name: str

    chat_model = get_llm_provider().chat_model()
    structured = chat_model.with_structured_output(_FunctionAnswer)

    context = (
        "--- calculator.py (chunk 0) ---\n"
        "def add(a, b):\n    return a + b\n\n"
        "def multiply(a, b):\n    return a * b\n"
    )
    result = await structured.ainvoke(
        f"Repository context:\n{context}\n\n"
        "Which function in this context would you call to multiply two numbers? "
        "Answer with just the function name."
    )
    assert "multiply" in result.function_name.lower()


async def test_llm_produces_a_valid_plan() -> None:
    """The real agent-facing client produces a schema-valid `Plan` for a
    concrete, simple task — the same call path `PlannerAgent` uses."""
    _require_live_credentials()
    client = build_default_llm_client()

    plan = await client.generate(
        system="You are a software engineering planner. Produce a concrete implementation plan.",
        user="Task: add a `subtract(a, b)` function to a Python module called calculator.py.",
        output_model=Plan,
    )
    assert isinstance(plan, Plan)
    assert plan.objective
    assert len(plan.steps) >= 1
