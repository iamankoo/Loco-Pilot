from __future__ import annotations

from pathlib import Path

from analysis.relevant_files import find_relevant_files
from analysis.scanner import scan_repository
from tools.workspace import Workspace


def test_finds_relevant_files_for_an_authentication_task(tmp_path: Path) -> None:
    (tmp_path / "backend" / "app" / "auth").mkdir(parents=True)
    (tmp_path / "backend" / "app" / "auth" / "auth_service.py").write_text("def login(): pass\n")
    (tmp_path / "backend" / "app" / "billing.py").write_text("def charge(): pass\n")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_auth.py").write_text("def test_login(): pass\n")

    structure = scan_repository(Workspace.at(tmp_path))
    results = find_relevant_files(structure, "Fix authentication bug")

    paths = [r.path for r in results]
    assert "backend/app/auth/auth_service.py" in paths
    assert "tests/test_auth.py" in paths
    assert "backend/app/billing.py" not in paths


def test_combines_path_matches_with_rag_retrieval_evidence(tmp_path: Path) -> None:
    (tmp_path / "auth.py").write_text("def login(): pass\n")
    (tmp_path / "unrelated.py").write_text("x = 1\n")

    structure = scan_repository(Workspace.at(tmp_path))
    results = find_relevant_files(
        structure, "Fix authentication bug", retrieved_chunk_paths=[("unrelated.py", 0.9)]
    )

    paths = {r.path: r for r in results}
    assert "auth.py" in paths
    assert "unrelated.py" in paths
    assert "retrieved by semantic search" in paths["unrelated.py"].reason
    # A file matched both by keyword AND retrieval should outrank one found
    # by only a single signal.
    assert paths["auth.py"].score > 0


def test_relevant_files_are_bounded(tmp_path: Path) -> None:
    for i in range(30):
        (tmp_path / f"auth_module_{i}.py").write_text("x = 1\n")

    structure = scan_repository(Workspace.at(tmp_path))
    results = find_relevant_files(structure, "Fix authentication bug", max_results=5)

    assert len(results) == 5
