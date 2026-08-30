from __future__ import annotations

from pydantic import BaseModel, Field

MAX_DIFF_CHARS = 200_000


class GitStatusInput(BaseModel):
    pass


class GitFileStatus(BaseModel):
    path: str
    status: str  # modified | added | deleted | renamed | copied | unmerged | untracked
    staged: bool


class GitStatusOutput(BaseModel):
    branch: str | None
    clean: bool
    files: list[GitFileStatus]


class GitDiffInput(BaseModel):
    staged: bool = False
    path: str | None = None
    # Phase 2.9: scope the diff to exactly these paths (e.g. the
    # execution's own FileChange paths) instead of the whole working
    # tree — so a diff shown to Reviewer never includes the user's own
    # pre-existing uncommitted changes, which the workspace is never
    # assumed to have started without. Ignored when `path` is also given.
    paths: list[str] = Field(default_factory=list)


class GitDiffOutput(BaseModel):
    diff: str
    truncated: bool
    # False means the workspace genuinely isn't a Git repository — a real,
    # common, non-error outcome for a freshly generated project (see
    # agents.reviewer, which reads actual file content directly instead in
    # that case), not a failure of the diff operation itself. `diff` is
    # always "" when this is False.
    is_git_repository: bool = True


class GitBranchInput(BaseModel):
    pass


class GitBranchOutput(BaseModel):
    current: str | None
    branches: list[str]


class GitCreateBranchInput(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    checkout: bool = True


class GitCreateBranchOutput(BaseModel):
    name: str
    checked_out: bool


class GitCommitInput(BaseModel):
    """Defined for interface completeness. Not registered as an agent-callable
    tool in Phase 1.2 — no automatic commits of agent changes yet."""

    message: str = Field(min_length=1)


class GitCommitOutput(BaseModel):
    commit_sha: str
    message: str
