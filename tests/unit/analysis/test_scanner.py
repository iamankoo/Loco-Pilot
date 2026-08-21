from __future__ import annotations

from pathlib import Path

import pytest

from analysis.scanner import ScanLimits, scan_repository
from tools.workspace import Workspace


def _workspace(tmp_path: Path) -> Workspace:
    return Workspace.at(tmp_path)


def test_scan_reports_structure_and_deterministic_ordering(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "src" / "b.py").write_text("b = 1\n")
    (tmp_path / "src" / "a.py").write_text("a = 1\n")
    (tmp_path / "tests" / "test_a.py").write_text("def test_a(): pass\n")
    (tmp_path / "README.md").write_text("# demo\n")
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n")

    structure = scan_repository(_workspace(tmp_path))

    assert "src/a.py" in structure.files
    assert "src/b.py" in structure.files
    # deterministic ordering: files within one directory come back sorted.
    assert structure.files.index("src/a.py") < structure.files.index("src/b.py")
    assert "tests" in structure.test_directories
    assert "pyproject.toml" in structure.dependency_manifests
    assert "README.md" in structure.documentation_files
    assert structure.file_count == len(structure.files)
    assert not structure.truncated


def test_scan_excludes_ignored_directories(tmp_path: Path) -> None:
    (tmp_path / "node_modules" / "pkg").mkdir(parents=True)
    (tmp_path / "node_modules" / "pkg" / "index.js").write_text("module.exports = {}\n")
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "HEAD").write_text("ref: refs/heads/main\n")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("x = 1\n")

    structure = scan_repository(_workspace(tmp_path))

    assert not any("node_modules" in f for f in structure.files)
    assert not any(f.startswith(".git/") for f in structure.files)
    assert "node_modules" in structure.ignored_directories
    assert "src/app.py" in structure.files
    assert structure.has_git is True


def test_scan_enforces_maximum_depth(tmp_path: Path) -> None:
    deep = tmp_path / "a" / "b" / "c" / "d"
    deep.mkdir(parents=True)
    (deep / "buried.py").write_text("x = 1\n")
    (tmp_path / "a" / "shallow.py").write_text("x = 1\n")

    structure = scan_repository(_workspace(tmp_path), ScanLimits(max_depth=2))

    assert not any("buried.py" in f for f in structure.files)
    assert any("shallow.py" in f for f in structure.files)
    assert any("depth" in w.lower() for w in structure.warnings)


def test_scan_enforces_maximum_file_count(tmp_path: Path) -> None:
    for i in range(10):
        (tmp_path / f"file_{i}.txt").write_text("x")

    structure = scan_repository(_workspace(tmp_path), ScanLimits(max_files=3))

    assert structure.file_count == 3
    assert structure.truncated is True
    assert any("file count" in w.lower() for w in structure.warnings)


def test_scan_does_not_follow_symlinked_directory_outside_workspace(tmp_path: Path) -> None:
    outside = tmp_path.parent / f"outside-{tmp_path.name}"
    outside.mkdir(exist_ok=True)
    (outside / "secret.txt").write_text("do not leak this\n")

    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    link = workspace_root / "escape"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("Symlink creation is not permitted in this environment.")

    structure = scan_repository(_workspace(workspace_root))

    assert not any("secret.txt" in f for f in structure.files)
