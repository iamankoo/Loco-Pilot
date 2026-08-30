"""Git tools: git_status, git_diff, git_branch, git_create_branch.

Every operation constructs its own fixed argv (never accepts a free-form
command string from the caller) and runs via `asyncio.create_subprocess_exec`
(never a shell), so there is no path to command injection and no way to
request a destructive operation (`reset --hard`, `clean -fd`, force-push,
history rewriting) through this tool layer — those commands simply have no
corresponding tool. `git_commit`'s schema exists for interface completeness
but is intentionally not registered in the default tool registry yet.
"""

from __future__ import annotations

import asyncio
import re

from tools.base import Permission, Tool, ToolContext, ToolError
from tools.git.schemas import (
    MAX_DIFF_CHARS,
    GitBranchInput,
    GitBranchOutput,
    GitCreateBranchInput,
    GitCreateBranchOutput,
    GitDiffInput,
    GitDiffOutput,
    GitFileStatus,
    GitStatusInput,
    GitStatusOutput,
)
from tools.workspace import Workspace, WorkspaceError

_GIT_TIMEOUT_SECONDS = 15
_VALID_BRANCH_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._\-/]*$")

_STATUS_CODE_LABELS = {
    "M": "modified",
    "A": "added",
    "D": "deleted",
    "R": "renamed",
    "C": "copied",
    "U": "unmerged",
    "?": "untracked",
    "!": "ignored",
}


async def _run_git(workspace: Workspace, args: list[str]) -> tuple[int, str, str]:
    try:
        process = await asyncio.create_subprocess_exec(
            "git",
            "-C",
            str(workspace.root),
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            process.communicate(), timeout=_GIT_TIMEOUT_SECONDS
        )
    except asyncio.TimeoutError as exc:
        raise ToolError(f"git {' '.join(args)} timed out after {_GIT_TIMEOUT_SECONDS}s") from exc
    except FileNotFoundError as exc:
        raise ToolError("git executable not found on PATH.") from exc

    return process.returncode or 0, stdout_bytes.decode("utf-8", errors="replace"), stderr_bytes.decode(
        "utf-8", errors="replace"
    )


async def _is_git_repo(workspace: Workspace) -> bool:
    code, stdout, _ = await _run_git(workspace, ["rev-parse", "--is-inside-work-tree"])
    return code == 0 and stdout.strip() == "true"


async def _ensure_git_repo(workspace: Workspace) -> None:
    if not await _is_git_repo(workspace):
        raise ToolError(f"Workspace is not a Git repository: {workspace.root}", code="NOT_A_GIT_REPOSITORY")


def _validate_branch_name(name: str) -> None:
    if not _VALID_BRANCH_NAME.match(name) or ".." in name or name.endswith("/") or name.endswith(".lock"):
        raise ToolError(f"Invalid branch name: {name!r}")


def _parse_porcelain_status(output: str) -> list[GitFileStatus]:
    files: list[GitFileStatus] = []
    for line in output.splitlines():
        if not line:
            continue
        staged_code, unstaged_code, rest = line[0], line[1], line[3:]
        path = rest.split(" -> ")[-1]  # renamed entries look like "old -> new"
        if staged_code == "?" and unstaged_code == "?":
            files.append(GitFileStatus(path=path, status="untracked", staged=False))
            continue
        if staged_code != " " and staged_code != "?":
            files.append(GitFileStatus(path=path, status=_STATUS_CODE_LABELS.get(staged_code, staged_code), staged=True))
        if unstaged_code != " " and unstaged_code != "?":
            files.append(GitFileStatus(path=path, status=_STATUS_CODE_LABELS.get(unstaged_code, unstaged_code), staged=False))
    return files


class GitStatusTool(Tool[GitStatusInput, GitStatusOutput]):
    name = "git_status"
    description = "Show the working tree status of the workspace's Git repository."
    permission = Permission.READ
    input_model = GitStatusInput
    output_model = GitStatusOutput

    async def run(self, tool_input: GitStatusInput, context: ToolContext) -> GitStatusOutput:
        await _ensure_git_repo(context.workspace)

        branch_code, branch_stdout, _ = await _run_git(context.workspace, ["branch", "--show-current"])
        branch = branch_stdout.strip() or None if branch_code == 0 else None

        code, stdout, stderr = await _run_git(context.workspace, ["status", "--porcelain=v1"])
        if code != 0:
            raise ToolError(f"git status failed: {stderr.strip()}")

        files = _parse_porcelain_status(stdout)
        return GitStatusOutput(branch=branch, clean=len(files) == 0, files=files)


class GitDiffTool(Tool[GitDiffInput, GitDiffOutput]):
    name = "git_diff"
    description = "Show the unified diff of unstaged (or staged) changes in the workspace."
    permission = Permission.READ
    input_model = GitDiffInput
    output_model = GitDiffOutput

    async def run(self, tool_input: GitDiffInput, context: ToolContext) -> GitDiffOutput:
        # A generated workspace legitimately not being a Git repository is a
        # normal, common outcome — not a tool failure — so this reports it
        # as a clean success with is_git_repository=False rather than
        # raising an "error" a caller/log would otherwise have to explain
        # away. Contrast with git_status/git_branch/git_create_branch (via
        # _ensure_git_repo), where the action genuinely cannot proceed at
        # all without a repository.
        if not await _is_git_repo(context.workspace):
            return GitDiffOutput(diff="", truncated=False, is_git_repository=False)

        args = ["diff"]
        if tool_input.staged:
            args.append("--staged")
        if tool_input.path:
            try:
                resolved = context.workspace.resolve(tool_input.path)
            except WorkspaceError as exc:
                raise ToolError(str(exc)) from exc
            args += ["--", str(resolved)]
        elif tool_input.paths:
            resolved_paths = []
            for p in tool_input.paths:
                try:
                    resolved_paths.append(str(context.workspace.resolve(p)))
                except WorkspaceError as exc:
                    raise ToolError(str(exc)) from exc
            args += ["--", *resolved_paths]

        code, stdout, stderr = await _run_git(context.workspace, args)
        if code != 0:
            raise ToolError(f"git diff failed: {stderr.strip()}")

        truncated = len(stdout) > MAX_DIFF_CHARS
        diff = stdout[:MAX_DIFF_CHARS]
        return GitDiffOutput(diff=diff, truncated=truncated)


class GitBranchTool(Tool[GitBranchInput, GitBranchOutput]):
    name = "git_branch"
    description = "List local branches in the workspace's Git repository."
    permission = Permission.READ
    input_model = GitBranchInput
    output_model = GitBranchOutput

    async def run(self, tool_input: GitBranchInput, context: ToolContext) -> GitBranchOutput:
        await _ensure_git_repo(context.workspace)

        code, stdout, stderr = await _run_git(context.workspace, ["branch", "--list"])
        if code != 0:
            raise ToolError(f"git branch failed: {stderr.strip()}")

        branches: list[str] = []
        current: str | None = None
        for line in stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            if line.startswith("* "):
                current = line[2:].strip()
                branches.append(current)
            else:
                branches.append(line)

        return GitBranchOutput(current=current, branches=branches)


class GitCreateBranchTool(Tool[GitCreateBranchInput, GitCreateBranchOutput]):
    name = "git_create_branch"
    description = "Create a new branch in the workspace's Git repository, optionally checking it out."
    permission = Permission.GIT_WRITE
    input_model = GitCreateBranchInput
    output_model = GitCreateBranchOutput

    async def run(self, tool_input: GitCreateBranchInput, context: ToolContext) -> GitCreateBranchOutput:
        _validate_branch_name(tool_input.name)
        await _ensure_git_repo(context.workspace)

        args = ["checkout", "-b", tool_input.name] if tool_input.checkout else ["branch", tool_input.name]
        code, _, stderr = await _run_git(context.workspace, args)
        if code != 0:
            raise ToolError(f"Failed to create branch {tool_input.name!r}: {stderr.strip()}")

        return GitCreateBranchOutput(name=tool_input.name, checked_out=tool_input.checkout)
