from __future__ import annotations

import uuid

import pytest

from backend.app.db.repositories.projects import create_project
from backend.app.db.repositories.repository_chunks import count_chunks_for_project
from rag.embeddings.hashing_provider import HashingEmbeddingProvider
from rag.exclusions import MAX_INDEXABLE_FILE_BYTES
from rag.ingestion.indexer import RepositoryIndexer
from tools.workspace import Workspace


async def test_index_repository_creates_chunks(db_session, tmp_workspace: Workspace) -> None:
    (tmp_workspace.root / "app.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    (tmp_workspace.root / "README.md").write_text("# Demo project\n", encoding="utf-8")

    project = await create_project(db_session, name=f"proj-{uuid.uuid4()}")
    indexer = RepositoryIndexer(HashingEmbeddingProvider())
    result = await indexer.index_repository(tmp_workspace, project.id, db_session)

    assert result.files_indexed == 2
    assert result.chunks_created >= 2

    count = await count_chunks_for_project(db_session, project.id)
    assert count == result.chunks_created


async def test_index_repository_excludes_ignored_dirs(db_session, tmp_workspace: Workspace) -> None:
    (tmp_workspace.root / ".git").mkdir()
    (tmp_workspace.root / ".git" / "config.py").write_text("ignored = True\n", encoding="utf-8")
    (tmp_workspace.root / "node_modules").mkdir()
    (tmp_workspace.root / "node_modules" / "lib.js").write_text("module.exports = {};\n", encoding="utf-8")
    (tmp_workspace.root / "main.py").write_text("print('real file')\n", encoding="utf-8")

    project = await create_project(db_session, name=f"proj-{uuid.uuid4()}")
    indexer = RepositoryIndexer(HashingEmbeddingProvider())
    result = await indexer.index_repository(tmp_workspace, project.id, db_session)

    assert result.files_indexed == 1


async def test_index_repository_ignores_unsupported_extensions(db_session, tmp_workspace: Workspace) -> None:
    (tmp_workspace.root / "image.png").write_bytes(b"\x89PNG\x00\x01\x02")
    (tmp_workspace.root / "code.py").write_text("x = 1\n", encoding="utf-8")

    project = await create_project(db_session, name=f"proj-{uuid.uuid4()}")
    indexer = RepositoryIndexer(HashingEmbeddingProvider())
    result = await indexer.index_repository(tmp_workspace, project.id, db_session)

    # .png is never discovered at all (unsupported extension) — only the
    # supported .py file is indexed.
    assert result.files_indexed == 1


async def test_index_repository_skips_binary_content_in_supported_extension(
    db_session, tmp_workspace: Workspace
) -> None:
    # A .py file that is actually binary content (null bytes) — discovered
    # because the extension is supported, then skipped once its content is
    # inspected.
    (tmp_workspace.root / "corrupt.py").write_bytes(b"\x00\x01\x02binary garbage")
    (tmp_workspace.root / "code.py").write_text("x = 1\n", encoding="utf-8")

    project = await create_project(db_session, name=f"proj-{uuid.uuid4()}")
    indexer = RepositoryIndexer(HashingEmbeddingProvider())
    result = await indexer.index_repository(tmp_workspace, project.id, db_session)

    assert result.files_indexed == 1
    assert result.files_skipped == 1


async def test_reindexing_a_file_replaces_its_chunks_not_duplicates(db_session, tmp_workspace: Workspace) -> None:
    (tmp_workspace.root / "app.py").write_text("x = 1\n", encoding="utf-8")
    project = await create_project(db_session, name=f"proj-{uuid.uuid4()}")
    indexer = RepositoryIndexer(HashingEmbeddingProvider())

    await indexer.index_repository(tmp_workspace, project.id, db_session)
    first_count = await count_chunks_for_project(db_session, project.id)

    await indexer.index_repository(tmp_workspace, project.id, db_session)
    second_count = await count_chunks_for_project(db_session, project.id)

    assert first_count == second_count == 1


async def test_index_repository_skips_empty_files(db_session, tmp_workspace: Workspace) -> None:
    (tmp_workspace.root / "empty.py").write_text("", encoding="utf-8")
    (tmp_workspace.root / "code.py").write_text("x = 1\n", encoding="utf-8")

    project = await create_project(db_session, name=f"proj-{uuid.uuid4()}")
    indexer = RepositoryIndexer(HashingEmbeddingProvider())
    result = await indexer.index_repository(tmp_workspace, project.id, db_session)

    assert result.files_indexed == 1
    assert result.files_skipped == 1


async def test_index_repository_skips_oversized_files(db_session, tmp_workspace: Workspace) -> None:
    (tmp_workspace.root / "huge.py").write_text("x" * (MAX_INDEXABLE_FILE_BYTES + 1), encoding="utf-8")
    (tmp_workspace.root / "code.py").write_text("x = 1\n", encoding="utf-8")

    project = await create_project(db_session, name=f"proj-{uuid.uuid4()}")
    indexer = RepositoryIndexer(HashingEmbeddingProvider())
    result = await indexer.index_repository(tmp_workspace, project.id, db_session)

    assert result.files_indexed == 1
    assert result.files_skipped == 1


async def test_index_repository_symlinked_directory_is_never_indexed(db_session, tmp_path) -> None:
    outside = tmp_path.parent / f"outside-index-{tmp_path.name}"
    outside.mkdir(exist_ok=True)
    (outside / "secret.py").write_text("SECRET_KEY = 'do-not-index-me'\n", encoding="utf-8")

    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    (workspace_root / "code.py").write_text("x = 1\n", encoding="utf-8")
    try:
        (workspace_root / "escape").symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("Symlink creation is not permitted in this environment.")

    project = await create_project(db_session, name=f"proj-{uuid.uuid4()}")
    indexer = RepositoryIndexer(HashingEmbeddingProvider())
    result = await indexer.index_repository(Workspace.at(workspace_root), project.id, db_session)

    # os.walk never follows a symlinked directory (followlinks=False,
    # the default) — the file outside the workspace is never discovered,
    # let alone indexed.
    assert result.files_indexed == 1


async def test_renaming_an_indexed_file_moves_its_chunks_not_duplicates(db_session, tmp_workspace: Workspace) -> None:
    """Phase 2.3 left a known limitation: renaming only reindexed the
    destination path, leaving the old path's stale chunks behind. Phase
    2.4 fixes this in `agents.graph._reindex_changed_files` (via
    `FileChange.source_path`) — this test verifies the underlying indexer
    primitive that fix relies on: clearing the old path's chunks once the
    file no longer exists there."""
    (tmp_workspace.root / "old_name.py").write_text("marker_epsilon = 1\n", encoding="utf-8")
    project = await create_project(db_session, name=f"proj-{uuid.uuid4()}")
    indexer = RepositoryIndexer(HashingEmbeddingProvider())
    await indexer.index_file(tmp_workspace, project.id, "old_name.py", db_session)
    assert await count_chunks_for_project(db_session, project.id) == 1

    (tmp_workspace.root / "old_name.py").rename(tmp_workspace.root / "new_name.py")

    # Reindexing both paths (as the graph now does for a "renamed" change)
    # clears the stale old-path entry and creates the new-path entry.
    old_path_chunk_count = await indexer.index_file(tmp_workspace, project.id, "old_name.py", db_session)
    new_path_chunk_count = await indexer.index_file(tmp_workspace, project.id, "new_name.py", db_session)

    assert old_path_chunk_count == 0
    assert new_path_chunk_count == 1
    assert await count_chunks_for_project(db_session, project.id) == 1
