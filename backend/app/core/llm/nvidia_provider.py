"""NVIDIA NIM provider (default: Nemotron Ultra), accessed
through NVIDIA's OpenAI-compatible chat-completions endpoint
(https://integrate.api.nvidia.com/v1), the same way QwenProvider talks to
DashScope — LLM_BASE_URL/LLM_MODEL/LLM_API_KEY point at it.
"""

from __future__ import annotations

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_openai import ChatOpenAI

from backend.app.core.config import Settings
from backend.app.core.errors import LLMConfigurationError
from backend.app.core.llm.base import LLMProvider


class NvidiaProvider(LLMProvider):
    name = "nvidia"

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def chat_model(self) -> BaseChatModel:
        settings = self._settings
        if not settings.llm_base_url:
            raise LLMConfigurationError("LLM_BASE_URL is not configured.")
        if not settings.llm_api_key:
            raise LLMConfigurationError("LLM_API_KEY is not configured.")

        return ChatOpenAI(
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key,
            model=settings.llm_model,
            temperature=settings.llm_temperature,
            timeout=settings.llm_request_timeout,
        )
