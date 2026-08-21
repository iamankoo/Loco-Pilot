"""Phase 2.3 — the strengthened/added filesystem tools: delete_file,
move_file, file_exists, diff generation on write/edit/delete, bounded
recursive listing, line-range reads, and filename-mode search. The
original single-level contracts already covered by
`test_filesystem_tools.py` are deliberately left untouched here.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tools.base import ToolContext, ToolError
from tools.filesystem.schemas import (
    DeleteFileInput,
    EditFileInput,
    FileExistsInput,
    ListDirectoryInput,
    MoveFileInput,
    ReadFileInput,
    SearchFilesInput,
    WriteFileInput,
)
from tools.filesystem.tools import (
    DeleteFileTool,
    EditFileTool,
    FileExistsTool,
    ListDirectoryTool,
    MoveFileTool,
    ReadFileTool,
    SearchFilesTool,
    WriteFileTool,
)
from tools.workspace import Workspace


@pytest.fixture
def ctx(tmp_workspace: Workspace) -> ToolContext:
    return ToolContext(workspace=tmp_workspace)


# ---- delete_file ----------------------------------------------------


async def test_delete_file_removes_a_file(ctx: ToolContext) -> None:
    await WriteFileTool().run(WriteFileInput(path="a.txt", content="x"), ctx)
    out = await DeleteFileTool().run(DeleteFileInput(path="a.txt"), ctx)
    assert out.deleted is True
    assert out.was_directory is False
    assert not (ctx.workspace.root / "a.txt").exists()


async def test_delete_file_generates_a_deletion_diff(ctx: ToolContext) -> None:
    await WriteFileTool().run(WriteFileInput(path="a.txt", content="hello\n"), ctx)
    out = await DeleteFileTool().run(DeleteFileInput(path="a.txt"), ctx)
    assert "-hello" in out.diff
    assert "/dev/null" in out.diff


async def test_delete_empty_directory(ctx: ToolContext) -> None:
    (ctx.workspace.root / "empty").mkdir()
    out = await DeleteFileTool().run(DeleteFileInput(path="empty"), ctx)
    assert out.deleted is True
    assert out.was_directory is True
    assert not (ctx.workspace.root / "empty").exists()


async def test_delete_nonempty_directory_requires_recursive_flag(ctx: ToolContext) -> None:
    await WriteFileTool().run(WriteFileInput(path="dir/a.txt", content="x"), ctx)
    with pytest.raises(ToolError) as exc_info:
        await DeleteFileTool().run(DeleteFileInput(path="dir"), ctx)
    assert exc_info.value.code == "DIRECTORY_NOT_EMPTY"
    assert (ctx.workspace.root / "dir").exists()


async def test_delete_nonempty_directory_recursive(ctx: ToolContext) -> None:
    await WriteFileTool().run(WriteFileInput(path="dir/a.txt", content="x"), ctx)
    await WriteFileTool().run(WriteFileInput(path="dir/sub/b.txt", content="y"), ctx)
    out = await DeleteFileTool().run(DeleteFileInput(path="dir", recursive=True), ctx)
    assert out.deleted is True
    assert not (ctx.workspace.root / "dir").exists()


async def test_delete_rejects_workspace_root(ctx: ToolContext) -> None:
    with pytest.raises(ToolError) as exc_info:
        await DeleteFileTool().run(DeleteFileInput(path="."), ctx)
    assert exc_info.value.code == "INVALID_PATH"
    assert ctx.workspace.root.exists()


async def test_delete_missing_file_raises_not_found(ctx: ToolContext) -> None:
    with pytest.raises(ToolError) as exc_info:
        await DeleteFileTool().run(DeleteFileInput(path="missing.txt"), ctx)
    assert exc_info.value.code == "FILE_NOT_FOUND"


async def test_delete_rejects_path_traversal(ctx: ToolContext) -> None:
    with pytest.raises(ToolError) as exc_info:
        await DeleteFileTool().run(DeleteFileInput(path="../outside.txt"), ctx)
    assert exc_info.value.code == "PATH_OUTSIDE_WORKSPACE"


async def test_delete_rejects_absolute_path(ctx: ToolContext) -> None:
    with pytest.raises(ToolError):
        await DeleteFileTool().run(DeleteFileInput(path="C:\\Windows\\System32"), ctx)


async def test_delete_rejects_symlink_escape(tmp_path: Path) -> None:
    outside = tmp_path.parent / f"outside-del-{tmp_path.name}"
    outside.mkdir(exist_ok=True)
    (outside / "secret.txt").write_text("secret")
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    try:
        (workspace_root / "link").symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("Symlink creation is not permitted in this environment.")

    context = ToolContext(workspace=Workspace.at(workspace_root))
    with pytest.raises(ToolError) as exc_info:
        await DeleteFileTool().run(DeleteFileInput(path="link/secret.txt"), context)
    assert exc_info.value.code == "PATH_OUTSIDE_WORKSPACE"
    assert (outside / "secret.txt").exists()


# ---- move_file --------------------------------------------------------


async def test_move_file_renames(ctx: ToolContext) -> None:
    await WriteFileTool().run(WriteFileInput(path="a.txt", content="x"), ctx)
    out = await MoveFileTool().run(MoveFileInput(source_path="a.txt", destination_path="b.txt"), ctx)
    assert out.moved is True
    assert out.was_directory is False
    assert not (ctx.workspace.root / "a.txt").exists()
    assert (ctx.workspace.root / "b.txt").read_text() == "x"


async def test_move_directory(ctx: ToolContext) -> None:
    await WriteFileTool().run(WriteFileInput(path="dir/a.txt", content="x"), ctx)
    out = await MoveFileTool().run(MoveFileInput(source_path="dir", destination_path="renamed"), ctx)
    assert out.was_directory is True
    assert (ctx.workspace.root / "renamed" / "a.txt").read_text() == "x"


async def test_move_rejects_destination_collision_without_overwrite(ctx: ToolContext) -> None:
    await WriteFileTool().run(WriteFileInput(path="a.txt", content="x"), ctx)
    await WriteFileTool().run(WriteFileInput(path="b.txt", content="y"), ctx)
    with pytest.raises(ToolError) as exc_info:
        await MoveFileTool().run(MoveFileInput(source_path="a.txt", destination_path="b.txt"), ctx)
    assert exc_info.value.code == "DESTINATION_EXISTS"
    assert (ctx.workspace.root / "b.txt").read_text() == "y"


async def test_move_overwrites_existing_file_when_explicitly_allowed(ctx: ToolContext) -> None:
    await WriteFileTool().run(WriteFileInput(path="a.txt", content="new"), ctx)
    await WriteFileTool().run(WriteFileInput(path="b.txt", content="old"), ctx)
    out = await MoveFileTool().run(MoveFileInput(source_path="a.txt", destination_path="b.txt", overwrite=True), ctx)
    assert out.moved is True
    assert (ctx.workspace.root / "b.txt").read_text() == "new"


async def test_move_never_silently_overwrites_a_directory(ctx: ToolContext) -> None:
    await WriteFileTool().run(WriteFileInput(path="a.txt", content="x"), ctx)
    (ctx.workspace.root / "b").mkdir()
    with pytest.raises(ToolError) as exc_info:
        await MoveFileTool().run(MoveFileInput(source_path="a.txt", destination_path="b", overwrite=True), ctx)
    assert exc_info.value.code == "DESTINATION_EXISTS"


async def test_move_rejects_source_path_traversal(ctx: ToolContext) -> None:
    with pytest.raises(ToolError) as exc_info:
        await MoveFileTool().run(MoveFileInput(source_path="../outside.txt", destination_path="a.txt"), ctx)
    assert exc_info.value.code == "PATH_OUTSIDE_WORKSPACE"


async def test_move_rejects_destination_path_traversal(ctx: ToolContext) -> None:
    await WriteFileTool().run(WriteFileInput(path="a.txt", content="x"), ctx)
    with pytest.raises(ToolError) as exc_info:
        await MoveFileTool().run(MoveFileInput(source_path="a.txt", destination_path="../escape.txt"), ctx)
    assert exc_info.value.code == "PATH_OUTSIDE_WORKSPACE"


async def test_move_rejects_workspace_root_as_source(ctx: ToolContext) -> None:
    with pytest.raises(ToolError):
        await MoveFileTool().run(MoveFileInput(source_path=".", destination_path="new-root"), ctx)


async def test_move_rejects_moving_directory_into_its_own_subtree(ctx: ToolContext) -> None:
    await WriteFileTool().run(WriteFileInput(path="dir/a.txt", content="x"), ctx)
    with pytest.raises(ToolError) as exc_info:
        await MoveFileTool().run(MoveFileInput(source_path="dir", destination_path="dir/nested"), ctx)
    assert exc_info.value.code == "INVALID_PATH"


async def test_move_rejects_missing_source(ctx: ToolContext) -> None:
    with pytest.raises(ToolError) as exc_info:
        await MoveFileTool().run(MoveFileInput(source_path="missing.txt", destination_path="a.txt"), ctx)
    assert exc_info.value.code == "FILE_NOT_FOUND"


# ---- file_exists --------------------------------------------------------


async def test_file_exists_reports_file(ctx: ToolContext) -> None:
    await WriteFileTool().run(WriteFileInput(path="a.txt", content="x"), ctx)
    out = await FileExistsTool().run(FileExistsInput(path="a.txt"), ctx)
    assert out.exists is True
    assert out.type == "file"


async def test_file_exists_reports_directory(ctx: ToolContext) -> None:
    (ctx.workspace.root / "sub").mkdir()
    out = await FileExistsTool().run(FileExistsInput(path="sub"), ctx)
    assert out.exists is True
    assert out.type == "directory"


async def test_file_exists_reports_missing_without_raising(ctx: ToolContext) -> None:
    out = await FileExistsTool().run(FileExistsInput(path="does-not-exist.txt"), ctx)
    assert out.exists is False
    assert out.type == "none"


async def test_file_exists_still_rejects_traversal(ctx: ToolContext) -> None:
    with pytest.raises(ToolError):
        await FileExistsTool().run(FileExistsInput(path="../outside.txt"), ctx)


# ---- diff generation on write/edit --------------------------------------


async def test_write_new_file_diff_shows_full_creation(ctx: ToolContext) -> None:
    out = await WriteFileTool().run(WriteFileInput(path="new.py", content="x = 1\n"), ctx)
    assert "+x = 1" in out.diff
    assert "/dev/null" in out.diff


async def test_write_overwrite_diff_shows_before_and_after(ctx: ToolContext) -> None:
    await WriteFileTool().run(WriteFileInput(path="a.py", content="x = 1\n"), ctx)
    out = await WriteFileTool().run(WriteFileInput(path="a.py", content="x = 2\n"), ctx)
    assert "-x = 1" in out.diff
    assert "+x = 2" in out.diff


async def test_edit_file_diff_reflects_the_actual_change(ctx: ToolContext) -> None:
    await WriteFileTool().run(WriteFileInput(path="a.py", content="value = 1\n"), ctx)
    out = await EditFileTool().run(EditFileInput(path="a.py", old_string="value = 1", new_string="value = 2"), ctx)
    assert "-value = 1" in out.diff
    assert "+value = 2" in out.diff


# ---- bounded recursive listing -------------------------------------------


async def test_list_directory_default_depth_is_immediate_children_only(ctx: ToolContext) -> None:
    await WriteFileTool().run(WriteFileInput(path="a.txt", content="a"), ctx)
    await WriteFileTool().run(WriteFileInput(path="sub/nested.txt", content="n"), ctx)
    out = await ListDirectoryTool().run(ListDirectoryInput(path="."), ctx)
    paths = {e.path for e in out.entries}
    assert "a.txt" in paths
    assert "sub" in paths
    assert "sub/nested.txt" not in paths


async def test_list_directory_recurses_to_requested_depth(ctx: ToolContext) -> None:
    await WriteFileTool().run(WriteFileInput(path="sub/nested.txt", content="n"), ctx)
    out = await ListDirectoryTool().run(ListDirectoryInput(path=".", max_depth=2), ctx)
    paths = {e.path for e in out.entries}
    assert "sub/nested.txt" in paths


async def test_list_directory_still_shows_but_never_descends_into_excluded_dirs(ctx: ToolContext) -> None:
    (ctx.workspace.root / "node_modules" / "pkg").mkdir(parents=True)
    (ctx.workspace.root / "node_modules" / "pkg" / "index.js").write_text("x")
    out = await ListDirectoryTool().run(ListDirectoryInput(path=".", max_depth=5), ctx)
    paths = {e.path for e in out.entries}
    assert "node_modules" in paths  # still listed as an entry at its own level
    assert not any("node_modules/" in p for p in paths)  # never recursed into


async def test_list_directory_enforces_max_results(ctx: ToolContext) -> None:
    for i in range(10):
        await WriteFileTool().run(WriteFileInput(path=f"file_{i}.txt", content="x"), ctx)
    out = await ListDirectoryTool().run(ListDirectoryInput(path=".", max_results=3), ctx)
    assert len(out.entries) == 3
    assert out.truncated is True


async def test_list_directory_ordering_is_deterministic(ctx: ToolContext) -> None:
    for name in ("banana.txt", "Apple.txt", "cherry.txt"):
        await WriteFileTool().run(WriteFileInput(path=name, content="x"), ctx)
    out1 = await ListDirectoryTool().run(ListDirectoryInput(path="."), ctx)
    out2 = await ListDirectoryTool().run(ListDirectoryInput(path="."), ctx)
    assert [e.name for e in out1.entries] == [e.name for e in out2.entries]


# ---- read_file line ranges ------------------------------------------------


async def test_read_file_line_range(ctx: ToolContext) -> None:
    await WriteFileTool().run(WriteFileInput(path="a.py", content="one\ntwo\nthree\nfour\n"), ctx)
    out = await ReadFileTool().run(ReadFileInput(path="a.py", start_line=2, end_line=3), ctx)
    assert out.content == "two\nthree"
    assert out.line_count == 4
    assert out.start_line == 2
    assert out.end_line == 3


async def test_read_file_line_range_from_start_only(ctx: ToolContext) -> None:
    await WriteFileTool().run(WriteFileInput(path="a.py", content="one\ntwo\nthree\n"), ctx)
    out = await ReadFileTool().run(ReadFileInput(path="a.py", start_line=2), ctx)
    assert out.content == "two\nthree"


async def test_read_file_rejects_out_of_bounds_line_range(ctx: ToolContext) -> None:
    await WriteFileTool().run(WriteFileInput(path="a.py", content="one\ntwo\n"), ctx)
    with pytest.raises(ToolError):
        await ReadFileTool().run(ReadFileInput(path="a.py", start_line=10, end_line=20), ctx)


# ---- search_files: filename mode ------------------------------------------


async def test_search_files_filename_mode_matches_path_not_content(ctx: ToolContext) -> None:
    await WriteFileTool().run(WriteFileInput(path="auth/auth_service.py", content="unrelated text"), ctx)
    await WriteFileTool().run(WriteFileInput(path="billing.py", content="auth mentioned here"), ctx)

    out = await SearchFilesTool().run(SearchFilesInput(query="auth", search_type="filename"), ctx)

    matched_paths = {m.path for m in out.matches}
    assert "auth/auth_service.py" in matched_paths
    assert "billing.py" not in matched_paths
    assert all(m.match_type == "filename" for m in out.matches)


async def test_search_files_both_mode_reports_either_kind(ctx: ToolContext) -> None:
    await WriteFileTool().run(WriteFileInput(path="auth_service.py", content="unrelated"), ctx)
    await WriteFileTool().run(WriteFileInput(path="billing.py", content="calls auth_service here"), ctx)

    out = await SearchFilesTool().run(SearchFilesInput(query="auth_service", search_type="both"), ctx)

    matched_paths = {m.path for m in out.matches}
    assert "auth_service.py" in matched_paths
    assert "billing.py" in matched_paths
