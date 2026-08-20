from __future__ import annotations

import uuid

from backend.app.db.repositories.projects import create_project
from backend.app.db.repositories.repository_chunks import count_chunks_for_project
from rag.embeddings.hashing_provider import HashingEmbeddingProvider
from rag.ingestion.indexer import RepositoryIndexer
from rag.retrieval.retriever import Retriever
from tools.workspace import Workspace


async def test_index_file_reindexes_only_the_one_file(db_session, tmp_workspace: Workspace) -> None:
    (tmp_workspace.root / "a.py").write_text("original_marker_alpha = 1\n", encoding="utf-8")
    (tmp_workspace.root / "b.py").write_text("unrelated_marker_beta = 2\n", encoding="utf-8")

    project = await create_project(db_session, name=f"proj-{uuid.uuid4()}")
    indexer = RepositoryIndexer(HashingEmbeddingProvider())
    await indexer.index_repository(tmp_workspace, project.id, db_session)
    baseline_count = await count_chunks_for_project(db_session, project.id)

    (tmp_workspace.root / "a.py").write_text("changed_marker_gamma = 99\n", encoding="utf-8")
    chunk_count = await indexer.index_file(tmp_workspace, project.id, "a.py", db_session)

    assert chunk_count == 1
    # total chunk count is unchanged (one file's chunk replaced, not duplicated, b.py untouched)
    assert await count_chunks_for_project(db_session, project.id) == baseline_count

    retriever = Retriever(HashingEmbeddingProvider())
    results = await retriever.retrieve("changed_marker_gamma", project_id=project.id, db=db_session, top_k=5)
    assert any("changed_marker_gamma" in r.content for r in results)
    assert not any("original_marker_alpha" in r.content for r in results)


async def test_index_file_on_a_newly_created_file(db_session, tmp_workspace: Workspace) -> None:
    project = await create_project(db_session, name=f"proj-{uuid.uuid4()}")
    indexer = RepositoryIndexer(HashingEmbeddingProvider())

    assert await count_chunks_for_project(db_session, project.id) == 0

    (tmp_workspace.root / "new_file.py").write_text("brand_new_marker = True\n", encoding="utf-8")
    chunk_count = await indexer.index_file(tmp_workspace, project.id, "new_file.py", db_session)

    assert chunk_count == 1
    assert await count_chunks_for_project(db_session, project.id) == 1


async def test_index_file_clears_chunks_for_a_file_that_becomes_unreadable(
    db_session, tmp_workspace: Workspace
) -> None:
    (tmp_workspace.root / "a.py").write_text("marker_delta = 1\n", encoding="utf-8")
    project = await create_project(db_session, name=f"proj-{uuid.uuid4()}")
    indexer = RepositoryIndexer(HashingEmbeddingProvider())
    await indexer.index_file(tmp_workspace, project.id, "a.py", db_session)
    assert await count_chunks_for_project(db_session, project.id) == 1

    # file becomes binary garbage — no longer indexable text
    (tmp_workspace.root / "a.py").write_bytes(b"\x00\x01\x02binary")
    chunk_count = await indexer.index_file(tmp_workspace, project.id, "a.py", db_session)

    assert chunk_count == 0
    assert await count_chunks_for_project(db_session, project.id) == 0
