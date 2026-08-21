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
    change_type: Literal["created", "modified", "deleted", "renamed", "failed"]
    detail: str
    # Only set for change_type="renamed" — the path the file moved FROM, so
    # the RAG index can clear its stale chunks (not just index the new
    # path). None for every other change type.
    source_path: str | None = None


class DeveloperResult(BaseModel):
    summary: str
    files_changed: list[FileChange] = Field(default_factory=list)


class TestResult(BaseModel):
    status: Literal["passed", "failed", "timed_out", "unavailable", "error"]
    # The detected test framework this result came from (e.g. "pytest",
    # "Jest"), when a real command actually ran — None for "unavailable".
    framework: str | None = None
    commands: list[str] = Field(default_factory=list)
    passed: int = 0
    failed: int = 0
    skipped: int = 0
    # Individual failing test identifiers parsed from real output (e.g.
    # "tests/test_auth.py::test_login"), bounded — not a claim of parsing
    # every framework's output format perfectly.
    failing_tests: list[str] = Field(default_factory=list)
    duration_ms: int | None = None
    errors: list[str] = Field(default_factory=list)
    summary: str


class DebugResult(BaseModel):
    root_cause: str
    proposed_fix: str
    confidence: Literal["low", "medium", "high"]
    files_to_change: list[str] = Field(default_factory=list)
    # Phase 2.7 additions — all defaulted so every existing
    # `DebugResult(root_cause=..., proposed_fix=..., confidence=...)`
    # construction site remains valid unchanged.
    #
    # A fuller narrative of what investigation actually found, distinct
    # from the terse `root_cause` conclusion.
    diagnosis: str = ""
    # Always computed deterministically from the real TestResult (see
    # `agents.failure_classification`), never left to the LLM's guess —
    # the actual test result is the authoritative evidence, the model
    # only assists with the narrative root_cause/proposed_fix.
    failure_class: Literal[
        "syntax_error", "import_error", "dependency_error", "assertion_failure",
        "type_error", "runtime_error", "configuration_error", "test_failure",
        "timeout", "build_failure", "environment_error", "unknown",
    ] = "unknown"
    # Derived from the real tool calls this turn actually made (read_file/
    # file_exists), never from the model's self-report of what it looked at.
    files_inspected: list[str] = Field(default_factory=list)
    attempt_number: int = 1
    # "fixed"/"unresolved" describe whether THIS attempt's fix actually
    # worked — only knowable once Tester runs again afterward, so the
    # Debugger's own turn only ever sets "diagnosed" (a fix was proposed),
    # "blocked" (no real investigative evidence could be gathered), or
    # "no_fix_needed" (no files_to_change — the model concluded no code
    # change is actually required). The outcome of the fix is reflected in
    # the next TestResult, not retroactively rewritten into this record.
    status: Literal["diagnosed", "fixed", "unresolved", "blocked", "no_fix_needed"] = "diagnosed"


class ReviewResult(BaseModel):
    verdict: Literal["approved", "changes_required"]
    summary: str
    issues: list[str] = Field(default_factory=list)
    regressions_observed: list[str] = Field(default_factory=list)
    # Phase 2.8 additions — all defaulted so every existing
    # `ReviewResult(verdict=..., summary=...)` construction site remains
    # valid unchanged.
    security_issues: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    # Always overridden by agents.reviewer with a deterministic value
    # derived from real evidence (security_issues present, or real test
    # status) rather than trusted from the LLM's own guess — never left
    # to sound more or less confident than the underlying evidence.
    risk: Literal["low", "medium", "high"] = "low"
    files_reviewed: int = 0
    tests_evaluated: int = 0
    # How many times the review loop has cycled when this result was
    # produced (1 = the first review of this change), independent of the
    # separate debug-retry counter.
    attempt_number: int = 1
