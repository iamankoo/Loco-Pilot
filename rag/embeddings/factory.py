"""Embedding provider factory — the only place that reads settings and
decides which concrete provider to construct."""

from __future__ import annotations

from functools import lru_cache

from backend.app.core.config import Settings, get_settings
from backend.app.core.errors import LocoPilotError
from rag.embeddings.base import EmbeddingProvider
from rag.embeddings.hashing_provider import HashingEmbeddingProvider
from rag.embeddings.openai_compatible_provider import OpenAICompatibleEmbeddingProvider


class EmbeddingConfigurationError(LocoPilotError):
    def __init__(self, message: str) -> None:
        super().__init__(message, status_code=503, code="embedding_configuration_error")


def build_embedding_provider(settings: Settings) -> EmbeddingProvider:
    if settings.embedding_provider == "hashing":
        return HashingEmbeddingProvider()
    if settings.embedding_provider == "openai_compatible":
        if not settings.embedding_base_url or not settings.embedding_api_key:
            raise EmbeddingConfigurationError(
                "EMBEDDING_BASE_URL and EMBEDDING_API_KEY are required for the openai_compatible embedding provider."
            )
        return OpenAICompatibleEmbeddingProvider(
            base_url=settings.embedding_base_url,
            api_key=settings.embedding_api_key,
            model=settings.embedding_model,
            dimension=settings.embedding_dimension,
        )
    raise ValueError(f"Unknown EMBEDDING_PROVIDER: {settings.embedding_provider!r}")


@lru_cache
def get_embedding_provider() -> EmbeddingProvider:
    return build_embedding_provider(get_settings())
