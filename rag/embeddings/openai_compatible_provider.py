"""An embedding provider for any OpenAI-compatible embeddings endpoint.

Configured entirely through settings (base URL / model / API key) — never
tied to one vendor. `dimensions` is passed through so the output width
matches the fixed pgvector column regardless of the model's native size.
"""

from __future__ import annotations

from langchain_openai import OpenAIEmbeddings

from rag.embeddings.base import EmbeddingProvider


class OpenAICompatibleEmbeddingProvider(EmbeddingProvider):
    name = "openai_compatible"

    def __init__(self, *, base_url: str, api_key: str, model: str, dimension: int) -> None:
        self.dimension = dimension
        self._client = OpenAIEmbeddings(base_url=base_url, api_key=api_key, model=model, dimensions=dimension)

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return await self._client.aembed_documents(texts)
