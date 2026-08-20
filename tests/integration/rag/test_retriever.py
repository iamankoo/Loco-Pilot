from __future__ import annotations

import uuid

from backend.app.db.repositories.projects import create_project
from rag.embeddings.hashing_provider import HashingEmbeddingProvider
from rag.ingestion.indexer import RepositoryIndexer
from rag.retrieval.retriever import Retriever
from tools.workspace import Workspace


async def test_retrieve_ranks_relevant_file_highest(db_session, tmp_workspace: Workspace) -> None:
    (tmp_workspace.root / "auth.py").write_text(
        "def authenticate_user(username, password):\n"
        "    \"\"\"Check user login credentials against the database.\"\"\"\n"
        "    return check_password_hash(username, password)\n",
        encoding="utf-8",
    )
    (tmp_workspace.root / "chart.py").write_text(
        "def render_chart(data):\n"
        "    \"\"\"Draw an axis, legend, and tooltip for the given chart data.\"\"\"\n"
        "    return build_svg(data)\n",
        encoding="utf-8",
    )

    project = await create_project(db_session, name=f"proj-{uuid.uuid4()}")
    indexer = RepositoryIndexer(HashingEmbeddingProvider())
    await indexer.index_repository(tmp_workspace, project.id, db_session)

    retriever = Retriever(HashingEmbeddingProvider())
    results = await retriever.retrieve(
        "authenticate user login password credentials", project_id=project.id, db=db_session, top_k=5
    )

    assert len(results) > 0
    assert results[0].file_path == "auth.py"


async def test_retrieve_respects_top_k(db_session, tmp_workspace: Workspace) -> None:
    for i in range(5):
        (tmp_workspace.root / f"file{i}.py").write_text(f"value_{i} = {i}\n", encoding="utf-8")

    project = await create_project(db_session, name=f"proj-{uuid.uuid4()}")
    indexer = RepositoryIndexer(HashingEmbeddingProvider())
    await indexer.index_repository(tmp_workspace, project.id, db_session)

    retriever = Retriever(HashingEmbeddingProvider())
    results = await retriever.retrieve("value", project_id=project.id, db=db_session, top_k=2)

    assert len(results) <= 2


async def test_retrieve_includes_metadata(db_session, tmp_workspace: Workspace) -> None:
    (tmp_workspace.root / "app.py").write_text("def foo():\n    pass\n", encoding="utf-8")
    project = await create_project(db_session, name=f"proj-{uuid.uuid4()}")
    indexer = RepositoryIndexer(HashingEmbeddingProvider())
    await indexer.index_repository(tmp_workspace, project.id, db_session)

    retriever = Retriever(HashingEmbeddingProvider())
    results = await retriever.retrieve("foo", project_id=project.id, db=db_session, top_k=5)

    assert results[0].metadata.get("language") == "py"
    assert "start_line" in results[0].metadata


async def test_retrieve_scoped_to_project(db_session, tmp_workspace: Workspace) -> None:
    (tmp_workspace.root / "app.py").write_text("unique_marker_xyz = 1\n", encoding="utf-8")
    project_a = await create_project(db_session, name=f"proj-a-{uuid.uuid4()}")
    project_b = await create_project(db_session, name=f"proj-b-{uuid.uuid4()}")

    indexer = RepositoryIndexer(HashingEmbeddingProvider())
    await indexer.index_repository(tmp_workspace, project_a.id, db_session)

    retriever = Retriever(HashingEmbeddingProvider())
    results_b = await retriever.retrieve("unique_marker_xyz", project_id=project_b.id, db=db_session, top_k=5)

    assert results_b == []
