from __future__ import annotations

import pytest

from tools.base import ToolContext, ToolError
from tools.git.schemas import GitBranchInput, GitCreateBranchInput, GitDiffInput, GitStatusInput
from tools.git.tools import GitBranchTool, GitCreateBranchTool, GitDiffTool, GitStatusTool
from tools.workspace import Workspace


@pytest.fixture
def ctx(tmp_git_workspace: Workspace) -> ToolContext:
    return ToolContext(workspace=tmp_git_workspace)


async def test_git_status_clean_repo(ctx: ToolContext) -> None:
    out = await GitStatusTool().run(GitStatusInput(), ctx)
    assert out.clean is True
    assert out.files == []


async def test_git_status_detects_untracked_file(ctx: ToolContext) -> None:
    (ctx.workspace.root / "new.txt").write_text("new")
    out = await GitStatusTool().run(GitStatusInput(), ctx)
    assert out.clean is False
    assert any(f.status == "untracked" and f.path == "new.txt" for f in out.files)


async def test_git_status_detects_modified_file(ctx: ToolContext) -> None:
    (ctx.workspace.root / "README.md").write_text("# changed\n")
    out = await GitStatusTool().run(GitStatusInput(), ctx)
    assert any(f.status == "modified" for f in out.files)


async def test_git_diff_shows_change(ctx: ToolContext) -> None:
    (ctx.workspace.root / "README.md").write_text("# changed\n")
    out = await GitDiffTool().run(GitDiffInput(), ctx)
    assert "changed" in out.diff


async def test_git_branch_lists_current(ctx: ToolContext) -> None:
    out = await GitBranchTool().run(GitBranchInput(), ctx)
    assert out.current is not None
    assert out.current in out.branches


async def test_git_create_branch(ctx: ToolContext) -> None:
    out = await GitCreateBranchTool().run(GitCreateBranchInput(name="feature/test", checkout=True), ctx)
    assert out.name == "feature/test"
    branches = await GitBranchTool().run(GitBranchInput(), ctx)
    assert "feature/test" in branches.branches
    assert branches.current == "feature/test"


async def test_git_create_branch_without_checkout(ctx: ToolContext) -> None:
    out = await GitCreateBranchTool().run(GitCreateBranchInput(name="feature/no-checkout", checkout=False), ctx)
    assert out.checked_out is False
    branches = await GitBranchTool().run(GitBranchInput(), ctx)
    assert branches.current != "feature/no-checkout"
    assert "feature/no-checkout" in branches.branches


async def test_git_create_branch_rejects_flag_like_name(ctx: ToolContext) -> None:
    with pytest.raises(ToolError):
        await GitCreateBranchTool().run(GitCreateBranchInput(name="-D", checkout=False), ctx)


async def test_git_create_branch_rejects_shell_metacharacters(ctx: ToolContext) -> None:
    with pytest.raises(ToolError):
        await GitCreateBranchTool().run(GitCreateBranchInput(name="a; rm -rf /", checkout=False), ctx)


async def test_git_status_rejects_non_git_workspace(tmp_workspace: Workspace) -> None:
    ctx = ToolContext(workspace=tmp_workspace)
    with pytest.raises(ToolError):
        await GitStatusTool().run(GitStatusInput(), ctx)


async def test_git_diff_rejects_non_git_workspace(tmp_workspace: Workspace) -> None:
    ctx = ToolContext(workspace=tmp_workspace)
    with pytest.raises(ToolError):
        await GitDiffTool().run(GitDiffInput(), ctx)


def test_no_git_tool_exposes_a_raw_command_field() -> None:
    """Destructive-command prevention is structural: no git tool input model
    accepts a free-form command/args field an agent could smuggle
    `--hard`/`-f`/history-rewriting flags through."""
    for model in (GitStatusInput, GitDiffInput, GitBranchInput, GitCreateBranchInput):
        fields = set(model.model_fields)
        assert "command" not in fields
        assert "args" not in fields
