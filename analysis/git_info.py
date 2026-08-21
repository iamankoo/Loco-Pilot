"""Git awareness for workspace intelligence — repository presence, current
branch, and working-tree status, without ever creating a branch or commit
(Phase 2.2 is read-only awareness; git workflow changes are a later phase).

Reuses the existing `git_status`/`git_branch` tool implementations
directly rather than re-implementing subprocess handling — this module is
orchestrator-internal deterministic infrastructure, not an LLM-driven
agent, so it calls the tools directly instead of going through the
permission-checked `BoundToolRunner` an agent's tool loop uses.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from tools.base import ToolContext, ToolError
from tools.git.schemas import GitBranchInput, GitStatusInput
from tools.git.tools import GitBranchTool, GitStatusTool
from tools.workspace import Workspace


class GitInfo(BaseModel):
    is_git_repository: bool = False
    current_branch: str | None = None
    clean: bool | None = None
    changed_files: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


async def inspect_git(workspace: Workspace) -> GitInfo:
    if not (workspace.root / ".git").exists():
        return GitInfo(is_git_repository=False)

    context = ToolContext(workspace=workspace)
    info = GitInfo(is_git_repository=True)

    try:
        status = await GitStatusTool().run(GitStatusInput(), context)
        info.clean = status.clean
        info.changed_files = [f.path for f in status.files][:50]
        info.current_branch = status.branch
    except ToolError as exc:
        info.warnings.append(f"git status failed: {exc}")

    if info.current_branch is None:
        try:
            branch = await GitBranchTool().run(GitBranchInput(), context)
            info.current_branch = branch.current
        except ToolError as exc:
            info.warnings.append(f"git branch failed: {exc}")

    return info
