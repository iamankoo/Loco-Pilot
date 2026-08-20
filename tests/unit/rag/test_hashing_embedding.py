from __future__ import annotations

import math

from rag.embeddings.hashing_provider import HashingEmbeddingProvider


async def test_dimension_is_fixed() -> None:
    provider = HashingEmbeddingProvider()
    [vector] = await provider.embed(["hello world"])
    assert len(vector) == provider.dimension


async def test_same_text_produces_identical_vector() -> None:
    provider = HashingEmbeddingProvider()
    [v1] = await provider.embed(["def foo(): return 1"])
    [v2] = await provider.embed(["def foo(): return 1"])
    assert v1 == v2


async def test_different_text_produces_different_vector() -> None:
    provider = HashingEmbeddingProvider()
    [v1] = await provider.embed(["def foo(): return 1"])
    [v2] = await provider.embed(["class Bar: pass"])
    assert v1 != v2


async def test_vector_is_l2_normalized() -> None:
    provider = HashingEmbeddingProvider()
    [vector] = await provider.embed(["some reasonably long piece of source code text here"])
    norm = math.sqrt(sum(v * v for v in vector))
    assert abs(norm - 1.0) < 1e-6


async def test_empty_text_produces_zero_vector() -> None:
    provider = HashingEmbeddingProvider()
    [vector] = await provider.embed([""])
    assert all(v == 0.0 for v in vector)


async def test_shared_vocabulary_increases_similarity() -> None:
    provider = HashingEmbeddingProvider()
    query, related, unrelated = await provider.embed(
        [
            "authenticate user login password",
            "def authenticate(user, password): check login credentials",
            "render chart axis legend tooltip",
        ]
    )

    def cosine(a: list[float], b: list[float]) -> float:
        return sum(x * y for x, y in zip(a, b))

    assert cosine(query, related) > cosine(query, unrelated)
