from __future__ import annotations

from pathlib import Path

import pytest

from tools.workspace import Workspace, WorkspaceError


def test_resolve_valid_relative_path(tmp_workspace: Workspace) -> None:
    (tmp_workspace.root / "sub").mkdir()
    assert tmp_workspace.resolve("sub") == tmp_workspace.root / "sub"


def test_resolve_nested_relative_path(tmp_workspace: Workspace) -> None:
    resolved = tmp_workspace.resolve("a/b/c.txt")
    assert resolved.parent.parent.name == "a"


def test_resolve_rejects_parent_traversal(tmp_workspace: Workspace) -> None:
    with pytest.raises(WorkspaceError):
        tmp_workspace.resolve("../outside.txt")


def test_resolve_rejects_deep_traversal(tmp_workspace: Workspace) -> None:
    with pytest.raises(WorkspaceError):
        tmp_workspace.resolve("a/../../b")


def test_resolve_rejects_absolute_posix_path(tmp_workspace: Workspace) -> None:
    with pytest.raises(WorkspaceError):
        tmp_workspace.resolve("/etc/passwd")


def test_resolve_rejects_absolute_windows_path(tmp_workspace: Workspace) -> None:
    with pytest.raises(WorkspaceError):
        tmp_workspace.resolve("C:\\Windows\\System32\\config")


def test_resolve_rejects_empty_path(tmp_workspace: Workspace) -> None:
    with pytest.raises(WorkspaceError):
        tmp_workspace.resolve("")


def test_workspace_at_rejects_missing_directory(tmp_path: Path) -> None:
    with pytest.raises(WorkspaceError):
        Workspace.at(tmp_path / "does-not-exist")


def test_relative_renders_workspace_relative_string(tmp_workspace: Workspace) -> None:
    target = tmp_workspace.resolve("a/b.txt")
    assert tmp_workspace.relative(target) == "a/b.txt"


def test_resolve_rejects_symlink_escape(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("secret")
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()

    try:
        (workspace_root / "link").symlink_to(outside, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"symlink creation not permitted in this environment: {exc}")

    workspace = Workspace.at(workspace_root)
    with pytest.raises(WorkspaceError):
        workspace.resolve("link/secret.txt")
