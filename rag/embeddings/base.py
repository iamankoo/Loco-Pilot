"""Provider-agnostic embedding interface, mirroring `backend.app.core.llm`'s
LLM provider pattern: agents/RAG code depend only on `EmbeddingProvider`,
never on a concrete implementation, so the backend can be swapped via
config (`EMBEDDING_PROVIDER`) without touching indexing/retrieval code.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import ClassVar


class EmbeddingProvider(ABC):
    name: ClassVar[str]
    dimension: ClassVar[int]

    @abstractmethod
    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Return one embedding vector per input text, each `self.dimension` long."""
        raise NotImplementedError
