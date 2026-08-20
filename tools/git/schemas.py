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


class GitDiffOutput(BaseModel):
    diff: str
    truncated: bool


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
