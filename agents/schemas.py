"""Structured input/output schemas for every agent.

Agents ask the LLM for these directly (via `StructuredLLMClient.generate`)
instead of parsing free-form text, so a malformed response is a validation
error the caller can catch and handle, not a silent misparse.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class Plan(BaseModel):
    objective: str
    assumptions: list[str] = Field(default_factory=list)
    files_likely_involved: list[str] = Field(default_factory=list)
    steps: list[str]
    testing_strategy: str
    risks: list[str] = Field(default_factory=list)


class ProposedEdit(BaseModel):
    """A deterministic unique-match replacement, applied via the `edit_file` tool."""

    path: str
    old_string: str
    new_string: str


class ProposedWrite(BaseModel):
    """A full file write (new file or full replacement), applied via `write_file`."""

    path: str
    content: str


class DeveloperPlan(BaseModel):
    """The Developer LLM's structured decision about what to change."""

    summary: str
    edits: list[ProposedEdit] = Field(default_factory=list)
    writes: list[ProposedWrite] = Field(default_factory=list)


class FileChange(BaseModel):
    path: str
    change_type: Literal["created", "modified", "failed"]
    detail: str


class DeveloperResult(BaseModel):
    summary: str
    files_changed: list[FileChange] = Field(default_factory=list)


class TestResult(BaseModel):
    status: Literal["passed", "failed", "unavailable", "error"]
    commands: list[str] = Field(default_factory=list)
    passed: int = 0
    failed: int = 0
    errors: list[str] = Field(default_factory=list)
    summary: str


class DebugResult(BaseModel):
    root_cause: str
    proposed_fix: str
    confidence: Literal["low", "medium", "high"]
    files_to_change: list[str] = Field(default_factory=list)


class ReviewResult(BaseModel):
    verdict: Literal["approved", "changes_required"]
    summary: str
    issues: list[str] = Field(default_factory=list)
    regressions_observed: list[str] = Field(default_factory=list)
