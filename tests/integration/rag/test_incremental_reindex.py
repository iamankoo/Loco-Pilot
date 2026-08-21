from __future__ import annotations

import uuid

from agents.graph import GraphDependencies, _reindex_changed_files
from agents.schemas import FileChange
from agents.state import ExecutionState
from backend.app.db.repositories.projects import create_project
from backend.app.db.repositories.repository_chunks import count_chunks_for_project
from rag.embeddings.hashing_provider import HashingEmbeddingProvider
from rag.ingestion.indexer import RepositoryIndexer
from rag.retrieval.retriever import Retriever
from tools.registry import build_default_registry
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


async def test_graph_reindex_on_rename_clears_old_path_and_indexes_new_path(
    db_session, tmp_workspace: Workspace
) -> None:
    """The Phase 2.3 known limitation ("renaming a file clears the
    destination path's RAG index entry but not the old path") fixed in
    Phase 2.4 via `FileChange.source_path` — exercised through the actual
    graph helper, not just the underlying indexer primitive."""
    (tmp_workspace.root / "old_name.py").write_text("marker_zeta = 1\n", encoding="utf-8")
    project = await create_project(db_session, name=f"proj-{uuid.uuid4()}")
    indexer = RepositoryIndexer(HashingEmbeddingProvider())
    await indexer.index_file(tmp_workspace, project.id, "old_name.py", db_session)
    assert await count_chunks_for_project(db_session, project.id) == 1

    (tmp_workspace.root / "old_name.py").rename(tmp_workspace.root / "new_name.py")

    state = ExecutionState(
        execution_id=str(uuid.uuid4()),
        project_id=str(project.id),
        user_task="rename the module",
        workspace_root=str(tmp_workspace.root),
    )
    deps = GraphDependencies(
        registry=build_default_registry(), llm_client=None, embedding_provider=HashingEmbeddingProvider(), db=db_session
    )
    update = {
        "files_changed": [
            FileChange(
                path="new_name.py", change_type="renamed", detail="renamed old_name.py -> new_name.py", source_path="old_name.py"
            )
        ]
    }

    await _reindex_changed_files(state, update, deps)

    assert await count_chunks_for_project(db_session, project.id) == 1
    retriever = Retriever(HashingEmbeddingProvider())
    results = await retriever.retrieve("marker_zeta", project_id=project.id, db=db_session, top_k=5)
    assert any(r.file_path == "new_name.py" for r in results)
    assert not any(r.file_path == "old_name.py" for r in results)
