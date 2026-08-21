"""Gemini provider, via Google's own Generative Language API (not an
OpenAI-compatible endpoint — no LLM_BASE_URL is needed or used here).
"""

from __future__ import annotations

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_google_genai import ChatGoogleGenerativeAI

from backend.app.core.config import Settings
from backend.app.core.errors import LLMConfigurationError
from backend.app.core.llm.base import LLMProvider


class GeminiProvider(LLMProvider):
    name = "gemini"

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def chat_model(self) -> BaseChatModel:
        settings = self._settings
        if not settings.llm_api_key:
            raise LLMConfigurationError("LLM_API_KEY is not configured.")

        return ChatGoogleGenerativeAI(
            model=settings.llm_model,
            google_api_key=settings.llm_api_key,
            temperature=settings.llm_temperature,
            timeout=settings.llm_request_timeout,
            max_retries=2,
        )
