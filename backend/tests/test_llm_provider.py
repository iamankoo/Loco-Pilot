from __future__ import annotations

import pytest

from backend.app.core.config import Settings
from backend.app.core.errors import LLMConfigurationError
from backend.app.core.llm.factory import build_llm_provider
from backend.app.core.llm.qwen_provider import QwenProvider


def test_factory_builds_qwen_provider_by_default() -> None:
    settings = Settings(_env_file=None)
    provider = build_llm_provider(settings)
    assert isinstance(provider, QwenProvider)
    assert provider.name == "qwen"


def test_factory_rejects_unknown_provider() -> None:
    settings = Settings(_env_file=None, llm_provider="does-not-exist")
    with pytest.raises(ValueError, match="Unknown LLM_PROVIDER"):
        build_llm_provider(settings)


def test_chat_model_requires_base_url_and_api_key() -> None:
    settings = Settings(_env_file=None, llm_base_url="", llm_api_key=None)
    provider = QwenProvider(settings)
    with pytest.raises(LLMConfigurationError):
        provider.chat_model()


def test_chat_model_builds_when_configured() -> None:
    settings = Settings(
        _env_file=None,
        llm_base_url="https://example.invalid/v1",
        llm_api_key="test-key",
        llm_model="qwen3-coder-plus",
    )
    provider = QwenProvider(settings)
    chat_model = provider.chat_model()
    assert chat_model.model_name == "qwen3-coder-plus"
