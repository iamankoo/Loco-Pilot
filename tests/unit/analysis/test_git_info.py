from __future__ import annotations

import subprocess
from pathlib import Path

from analysis.git_info import inspect_git
from tools.workspace import Workspace


async def test_detects_git_repository_and_branch(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=tmp_path, check=True, capture_output=True)
    (tmp_path / "README.md").write_text("# demo\n")
    subprocess.run(["git", "add", "README.md"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-q", "-m", "initial"], cwd=tmp_path, check=True, capture_output=True)

    info = await inspect_git(Workspace.at(tmp_path))

    assert info.is_git_repository is True
    assert info.current_branch is not None
    assert info.clean is True


async def test_detects_non_git_project(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("# demo\n")

    info = await inspect_git(Workspace.at(tmp_path))

    assert info.is_git_repository is False
    assert info.current_branch is None
