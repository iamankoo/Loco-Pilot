"""End-to-end Qwen3-Coder connectivity smoke test.

Skips gracefully when LLM_API_KEY / LLM_BASE_URL are not configured, so the
rest of the suite never depends on an external API being reachable.
"""

from __future__ import annotations

import pytest

from backend.app.core.config import get_settings
from backend.app.core.llm.factory import get_llm_provider


async def test_qwen_smoke() -> None:
    settings = get_settings()
    if not settings.llm_api_key or not settings.llm_base_url:
        pytest.skip("LLM_API_KEY/LLM_BASE_URL not configured; skipping live LLM smoke test.")

    provider = get_llm_provider()
    chat_model = provider.chat_model()

    response = await chat_model.ainvoke("Reply with exactly one word: ok")
    assert response.content
    assert len(str(response.content)) < 200
