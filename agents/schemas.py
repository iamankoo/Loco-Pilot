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
    # A glob (relative to the workspace root, e.g. "dist/*.whl") for a build
    # artifact this task is expected to produce, if any. None means no
    # artifact is expected — the execution completes normally either way.
    expected_artifact_glob: str | None = None


class DeveloperPlan(BaseModel):
    """The Developer LLM's final summary after its tool-calling turn.

    Unlike Phase 1.3/1.4, edits/writes are no longer a separate listed
    decision the agent applies afterward — the LLM makes those tool calls
    itself during `generate_with_tools`'s loop (see `agents/developer.py`);
    this is just its closing summary of what it did.
    """

    summary: str


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
