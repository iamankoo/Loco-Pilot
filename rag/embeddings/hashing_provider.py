"""A free, local, deterministic embedding provider.

This is a feature-hashing bag-of-words vector (hashed term frequencies,
L2-normalized) — not a learned semantic embedding. It exists so the full
RAG pipeline (chunk -> embed -> store -> cosine-similarity retrieve) is
genuinely exercised, end to end, with zero external dependencies, no
download, and no API key. Shared/related vocabulary between a query and a
chunk still produces higher cosine similarity, so retrieval behaves
sensibly for keyword-bearing code/task queries — but it has none of a real
model's understanding of meaning or synonyms. Swap in a real model (a
local sentence-transformer or an OpenAI-compatible embeddings endpoint via
`OpenAICompatibleEmbeddingProvider`) by setting `EMBEDDING_PROVIDER`; no
RAG code needs to change.
"""

from __future__ import annotations

import hashlib
import math
import re

from rag.embeddings.base import EmbeddingProvider

_TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*|[0-9]+")


class HashingEmbeddingProvider(EmbeddingProvider):
    name = "hashing"
    dimension = 384

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(text) for text in texts]

    def _embed_one(self, text: str) -> list[float]:
        vector = [0.0] * self.dimension
        tokens = _TOKEN_RE.findall(text.lower())
        for token in tokens:
            index = int(hashlib.blake2b(token.encode("utf-8"), digest_size=4).hexdigest(), 16) % self.dimension
            vector[index] += 1.0

        norm = math.sqrt(sum(v * v for v in vector))
        if norm > 0:
            vector = [v / norm for v in vector]
        return vector
