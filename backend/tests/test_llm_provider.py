from __future__ import annotations

import pytest

from backend.app.core.config import Settings
from backend.app.core.errors import LLMConfigurationError
from backend.app.core.llm.factory import build_llm_provider
from backend.app.core.llm.gemini_provider import GeminiProvider
from backend.app.core.llm.qwen_provider import QwenProvider


def test_factory_builds_gemini_provider_by_default() -> None:
    settings = Settings(_env_file=None)
    provider = build_llm_provider(settings)
    assert isinstance(provider, GeminiProvider)
    assert provider.name == "gemini"


def test_factory_builds_qwen_provider_when_selected() -> None:
    """Provider-agnostic: Qwen remains fully supported and selectable
    purely through configuration, even though Gemini is now the default."""
    settings = Settings(_env_file=None, llm_provider="qwen")
    provider = build_llm_provider(settings)
    assert isinstance(provider, QwenProvider)
    assert provider.name == "qwen"


def test_factory_rejects_unknown_provider() -> None:
    settings = Settings(_env_file=None, llm_provider="does-not-exist")
    with pytest.raises(ValueError, match="Unknown LLM_PROVIDER"):
        build_llm_provider(settings)


def test_qwen_chat_model_requires_base_url_and_api_key() -> None:
    settings = Settings(_env_file=None, llm_base_url="", llm_api_key=None)
    provider = QwenProvider(settings)
    with pytest.raises(LLMConfigurationError):
        provider.chat_model()


def test_qwen_chat_model_builds_when_configured() -> None:
    settings = Settings(
        _env_file=None,
        llm_base_url="https://example.invalid/v1",
        llm_api_key="test-key",
        llm_model="qwen3-coder-plus",
    )
    provider = QwenProvider(settings)
    chat_model = provider.chat_model()
    assert chat_model.model_name == "qwen3-coder-plus"


def test_gemini_chat_model_requires_api_key() -> None:
    settings = Settings(_env_file=None, llm_provider="gemini", llm_api_key=None)
    provider = GeminiProvider(settings)
    with pytest.raises(LLMConfigurationError):
        provider.chat_model()


def test_gemini_chat_model_builds_when_configured() -> None:
    settings = Settings(
        _env_file=None,
        llm_provider="gemini",
        llm_api_key="test-key",
        llm_model="gemini-pro-latest",
    )
    provider = GeminiProvider(settings)
    chat_model = provider.chat_model()
    assert chat_model.model == "models/gemini-pro-latest"


def test_gemini_chat_model_does_not_require_base_url() -> None:
    settings = Settings(_env_file=None, llm_provider="gemini", llm_base_url="", llm_api_key="test-key")
    provider = GeminiProvider(settings)
    provider.chat_model()  # must not raise despite no LLM_BASE_URL
