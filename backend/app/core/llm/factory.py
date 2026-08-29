"""LLM provider factory.

Call sites (agents, tools, API routes) call `get_llm_provider()` and never
reference a concrete provider class or vendor name. Adding a new provider
means registering it in `_PROVIDERS`, not touching any caller.
"""

from __future__ import annotations

from functools import lru_cache

from backend.app.core.config import Settings, get_settings
from backend.app.core.llm.base import LLMProvider
from backend.app.core.llm.gemini_provider import GeminiProvider
from backend.app.core.llm.nvidia_provider import NvidiaProvider
from backend.app.core.llm.qwen_provider import QwenProvider

_PROVIDERS: dict[str, type[LLMProvider]] = {
    "qwen": QwenProvider,
    "gemini": GeminiProvider,
    "nvidia": NvidiaProvider,
}


def build_llm_provider(settings: Settings) -> LLMProvider:
    provider_cls = _PROVIDERS.get(settings.llm_provider)
    if provider_cls is None:
        known = ", ".join(sorted(_PROVIDERS))
        raise ValueError(f"Unknown LLM_PROVIDER '{settings.llm_provider}'. Known providers: {known}")
    return provider_cls(settings)


@lru_cache
def get_llm_provider() -> LLMProvider:
    return build_llm_provider(get_settings())
