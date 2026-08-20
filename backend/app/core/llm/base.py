"""Provider-agnostic LLM interface.

Agents must depend only on `LLMProvider` (via `get_llm_provider`), never on
a concrete provider class. Swapping the underlying model/vendor is a config
change (`LLM_PROVIDER`, `LLM_BASE_URL`, `LLM_MODEL`, `LLM_API_KEY`), not a
code change in agent modules.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from langchain_core.language_models.chat_models import BaseChatModel


class LLMProvider(ABC):
    """A named provider capable of producing a LangChain chat model."""

    name: str

    @abstractmethod
    def chat_model(self) -> BaseChatModel:
        """Return a configured, ready-to-use LangChain chat model instance."""
        raise NotImplementedError
