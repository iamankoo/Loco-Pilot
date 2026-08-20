from __future__ import annotations

import uuid
from typing import TypedDict

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.models.repository_chunk import RepositoryChunk


class ChunkInput(TypedDict):
    chunk_index: int
    content: str
    embedding: list[float]
    metadata: dict | None


async def replace_chunks_for_file(
    db: AsyncSession,
    *,
    project_id: uuid.UUID,
    file_path: str,
    chunks: list[ChunkInput],
) -> list[RepositoryChunk]:
    """Deletes any existing chunks for this file and inserts the new set —
    a simple, correct re-indexing strategy: re-indexing a changed file
    never leaves stale chunks behind."""
    await db.execute(
        delete(RepositoryChunk).where(
            RepositoryChunk.project_id == project_id, RepositoryChunk.file_path == file_path
        )
    )
    rows = [
        RepositoryChunk(
            project_id=project_id,
            file_path=file_path,
            chunk_index=c["chunk_index"],
            content=c["content"],
            embedding=c["embedding"],
            chunk_metadata=c.get("metadata"),
        )
        for c in chunks
    ]
    db.add_all(rows)
    await db.commit()
    for row in rows:
        await db.refresh(row)
    return rows


async def delete_chunks_for_project(db: AsyncSession, project_id: uuid.UUID) -> None:
    await db.execute(delete(RepositoryChunk).where(RepositoryChunk.project_id == project_id))
    await db.commit()


async def similarity_search(
    db: AsyncSession,
    *,
    project_id: uuid.UUID,
    query_embedding: list[float],
    top_k: int = 8,
) -> list[tuple[RepositoryChunk, float]]:
    """Returns (chunk, cosine_distance) pairs ordered nearest-first."""
    distance = RepositoryChunk.embedding.cosine_distance(query_embedding)
    stmt = (
        select(RepositoryChunk, distance.label("distance"))
        .where(RepositoryChunk.project_id == project_id)
        .order_by(distance)
        .limit(top_k)
    )
    result = await db.execute(stmt)
    return [(row[0], row[1]) for row in result.all()]


async def count_chunks_for_project(db: AsyncSession, project_id: uuid.UUID) -> int:
    stmt = select(func.count()).select_from(RepositoryChunk).where(RepositoryChunk.project_id == project_id)
    result = await db.execute(stmt)
    return result.scalar_one()
