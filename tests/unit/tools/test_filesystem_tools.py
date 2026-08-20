from __future__ import annotations

import pytest

from tools.base import ToolContext, ToolError
from tools.filesystem.schemas import (
    EditFileInput,
    ListDirectoryInput,
    ReadFileInput,
    SearchFilesInput,
    WriteFileInput,
)
from tools.filesystem.tools import (
    EditFileTool,
    ListDirectoryTool,
    ReadFileTool,
    SearchFilesTool,
    WriteFileTool,
)
from tools.workspace import Workspace


@pytest.fixture
def ctx(tmp_workspace: Workspace) -> ToolContext:
    return ToolContext(workspace=tmp_workspace)


async def test_write_then_read_file(ctx: ToolContext) -> None:
    write_out = await WriteFileTool().run(WriteFileInput(path="a.txt", content="hello"), ctx)
    assert write_out.created is True
    assert write_out.bytes_written == 5

    read_out = await ReadFileTool().run(ReadFileInput(path="a.txt"), ctx)
    assert read_out.content == "hello"
    assert read_out.truncated is False


async def test_write_creates_parent_dirs(ctx: ToolContext) -> None:
    out = await WriteFileTool().run(WriteFileInput(path="nested/dir/file.txt", content="x"), ctx)
    assert out.created is True
    assert (ctx.workspace.root / "nested" / "dir" / "file.txt").exists()


async def test_write_rejects_overwrite_false_when_exists(ctx: ToolContext) -> None:
    await WriteFileTool().run(WriteFileInput(path="a.txt", content="one"), ctx)
    with pytest.raises(ToolError):
        await WriteFileTool().run(WriteFileInput(path="a.txt", content="two", overwrite=False), ctx)


async def test_write_rejects_path_traversal(ctx: ToolContext) -> None:
    with pytest.raises(ToolError):
        await WriteFileTool().run(WriteFileInput(path="../outside.txt", content="x"), ctx)


async def test_read_missing_file_raises(ctx: ToolContext) -> None:
    with pytest.raises(ToolError):
        await ReadFileTool().run(ReadFileInput(path="missing.txt"), ctx)


async def test_read_rejects_path_traversal(ctx: ToolContext) -> None:
    with pytest.raises(ToolError):
        await ReadFileTool().run(ReadFileInput(path="../outside.txt"), ctx)


async def test_read_enforces_size_limit_and_truncates(ctx: ToolContext) -> None:
    await WriteFileTool().run(WriteFileInput(path="big.txt", content="x" * 5000), ctx)
    out = await ReadFileTool().run(ReadFileInput(path="big.txt", max_bytes=1000), ctx)
    assert out.truncated is True
    assert len(out.content) == 1000


async def test_read_rejects_binary_file(ctx: ToolContext) -> None:
    (ctx.workspace.root / "bin.dat").write_bytes(b"\x00\x01\x02binary")
    with pytest.raises(ToolError):
        await ReadFileTool().run(ReadFileInput(path="bin.dat"), ctx)


async def test_edit_file_replaces_unique_match(ctx: ToolContext) -> None:
    await WriteFileTool().run(WriteFileInput(path="a.py", content="value = 1\n"), ctx)
    out = await EditFileTool().run(
        EditFileInput(path="a.py", old_string="value = 1", new_string="value = 2"), ctx
    )
    assert out.replaced is True
    read_out = await ReadFileTool().run(ReadFileInput(path="a.py"), ctx)
    assert "value = 2" in read_out.content


async def test_edit_file_rejects_missing_match(ctx: ToolContext) -> None:
    await WriteFileTool().run(WriteFileInput(path="a.py", content="value = 1\n"), ctx)
    with pytest.raises(ToolError):
        await EditFileTool().run(EditFileInput(path="a.py", old_string="not there", new_string="x"), ctx)


async def test_edit_file_rejects_non_unique_match(ctx: ToolContext) -> None:
    await WriteFileTool().run(WriteFileInput(path="a.py", content="x = 1\nx = 1\n"), ctx)
    with pytest.raises(ToolError):
        await EditFileTool().run(EditFileInput(path="a.py", old_string="x = 1", new_string="x = 2"), ctx)


async def test_list_directory(ctx: ToolContext) -> None:
    await WriteFileTool().run(WriteFileInput(path="a.txt", content="a"), ctx)
    await WriteFileTool().run(WriteFileInput(path="sub/b.txt", content="b"), ctx)
    out = await ListDirectoryTool().run(ListDirectoryInput(path="."), ctx)
    names = {e.name for e in out.entries}
    assert "a.txt" in names
    assert "sub" in names


async def test_list_directory_rejects_missing_path(ctx: ToolContext) -> None:
    with pytest.raises(ToolError):
        await ListDirectoryTool().run(ListDirectoryInput(path="does-not-exist"), ctx)


async def test_search_files_finds_match(ctx: ToolContext) -> None:
    await WriteFileTool().run(WriteFileInput(path="a.py", content="def hello():\n    return 'world'\n"), ctx)
    out = await SearchFilesTool().run(SearchFilesInput(query="hello"), ctx)
    assert len(out.matches) == 1
    assert out.matches[0].path == "a.py"
    assert out.matches[0].line_number == 1


async def test_search_files_excludes_git_dir(ctx: ToolContext) -> None:
    (ctx.workspace.root / ".git").mkdir()
    (ctx.workspace.root / ".git" / "config").write_text("needle")
    (ctx.workspace.root / "app.py").write_text("needle")
    out = await SearchFilesTool().run(SearchFilesInput(query="needle"), ctx)
    assert all(".git" not in m.path for m in out.matches)
    assert any(m.path == "app.py" for m in out.matches)


async def test_search_files_respects_glob(ctx: ToolContext) -> None:
    await WriteFileTool().run(WriteFileInput(path="a.py", content="needle"), ctx)
    await WriteFileTool().run(WriteFileInput(path="a.txt", content="needle"), ctx)
    out = await SearchFilesTool().run(SearchFilesInput(query="needle", glob="*.py"), ctx)
    assert all(m.path.endswith(".py") for m in out.matches)
