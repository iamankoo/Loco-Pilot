from __future__ import annotations

import uuid

from backend.app.db.models.repository_chunk import EMBEDDING_DIMENSION
from backend.app.db.repositories.projects import create_project
from backend.app.db.repositories.repository_chunks import (
    count_chunks_for_project,
    delete_chunks_for_project,
    replace_chunks_for_file,
    similarity_search,
)

# Matches the real pgvector column width rather than re-hardcoding a magic
# number that would silently drift out of sync with a future schema change.
_DIM = EMBEDDING_DIMENSION


def _vec(seed: float) -> list[float]:
    vector = [0.0] * _DIM
    vector[0] = seed
    return vector


async def test_replace_chunks_for_file_inserts_rows(db_session) -> None:
    project = await create_project(db_session, name=f"proj-{uuid.uuid4()}")
    rows = await replace_chunks_for_file(
        db_session,
        project_id=project.id,
        file_path="a.py",
        chunks=[{"chunk_index": 0, "content": "x = 1", "embedding": _vec(1.0), "metadata": None}],
    )
    assert len(rows) == 1
    assert await count_chunks_for_project(db_session, project.id) == 1


async def test_replace_chunks_for_file_removes_stale_chunks(db_session) -> None:
    project = await create_project(db_session, name=f"proj-{uuid.uuid4()}")
    await replace_chunks_for_file(
        db_session,
        project_id=project.id,
        file_path="a.py",
        chunks=[
            {"chunk_index": 0, "content": "x = 1", "embedding": _vec(1.0), "metadata": None},
            {"chunk_index": 1, "content": "y = 2", "embedding": _vec(2.0), "metadata": None},
        ],
    )
    assert await count_chunks_for_project(db_session, project.id) == 2

    # re-index with only one chunk now — the second must be gone, not orphaned
    await replace_chunks_for_file(
        db_session,
        project_id=project.id,
        file_path="a.py",
        chunks=[{"chunk_index": 0, "content": "x = 1", "embedding": _vec(1.0), "metadata": None}],
    )
    assert await count_chunks_for_project(db_session, project.id) == 1


async def test_delete_chunks_for_project(db_session) -> None:
    project = await create_project(db_session, name=f"proj-{uuid.uuid4()}")
    await replace_chunks_for_file(
        db_session,
        project_id=project.id,
        file_path="a.py",
        chunks=[{"chunk_index": 0, "content": "x = 1", "embedding": _vec(1.0), "metadata": None}],
    )
    await delete_chunks_for_project(db_session, project.id)
    assert await count_chunks_for_project(db_session, project.id) == 0


async def test_similarity_search_orders_by_distance(db_session) -> None:
    project = await create_project(db_session, name=f"proj-{uuid.uuid4()}")
    await replace_chunks_for_file(
        db_session,
        project_id=project.id,
        file_path="near.py",
        chunks=[{"chunk_index": 0, "content": "near", "embedding": _vec(1.0), "metadata": None}],
    )
    await replace_chunks_for_file(
        db_session,
        project_id=project.id,
        file_path="far.py",
        chunks=[{"chunk_index": 0, "content": "far", "embedding": _vec(-1.0), "metadata": None}],
    )

    results = await similarity_search(db_session, project_id=project.id, query_embedding=_vec(1.0), top_k=2)
    assert results[0][0].file_path == "near.py"
    assert results[0][1] < results[1][1]  # nearest has the smallest distance
