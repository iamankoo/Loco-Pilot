"""Semantic retrieval: query -> embed -> pgvector cosine search -> ranked chunks.

Pure vector similarity today. `RetrievedChunk` carries enough (file_path,
chunk_index, score) that a future hybrid lexical+semantic ranker can merge
in `search_files`-style keyword hits without changing this return type.
"""

from __future__ import annotations

import uuid

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.repositories.repository_chunks import similarity_search
from rag.embeddings.base import EmbeddingProvider

DEFAULT_TOP_K = 8


class RetrievedChunk(BaseModel):
    file_path: str
    content: str
    chunk_index: int
    score: float
    metadata: dict = Field(default_factory=dict)


class Retriever:
    def __init__(self, embedding_provider: EmbeddingProvider) -> None:
        self._embedding_provider = embedding_provider

    async def retrieve(
        self,
        query: str,
        *,
        project_id: uuid.UUID,
        db: AsyncSession,
        top_k: int = DEFAULT_TOP_K,
    ) -> list[RetrievedChunk]:
        [query_embedding] = await self._embedding_provider.embed([query])
        rows = await similarity_search(db, project_id=project_id, query_embedding=query_embedding, top_k=top_k)

        return [
            RetrievedChunk(
                file_path=chunk.file_path,
                content=chunk.content,
                chunk_index=chunk.chunk_index,
                score=1.0 - distance,
                metadata=chunk.chunk_metadata or {},
            )
            for chunk, distance in rows
        ]
