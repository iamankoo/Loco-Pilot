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
    # Set only when the task implies the app should actually run somewhere
    # reachable (e.g. "...and run it on local host") — argv (never a shell
    # string), the same contract as execute_terminal_command. Tester's own
    # deterministic code (never the LLM directly) is what actually launches
    # this, inside the same sandbox isolation every other command gets, with
    # the resulting port published to 127.0.0.1 only (see
    # execution.docker.runtime.ManagedRuntime). The process this starts must
    # bind 0.0.0.0 internally (not 127.0.0.1) for Docker's own port-publish
    # to reach it — that only affects the container-internal bind; the host
    # exposure stays loopback-only regardless. None means no runtime is
    # expected — Tester behaves exactly as before this field existed.
    run_command: list[str] | None = None
    run_port: int | None = Field(default=None, gt=0, le=65535)


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
    # Which kind of deterministic verification actually produced this
    # result — lets Reviewer/the UI distinguish "a conventional test suite
    # ran" from "no test framework exists, so Tester verified the static
    # entry point/assets/runtime instead" from neither having happened.
    verification_kind: Literal["automated_tests", "static_site", "none"] = "automated_tests"
    # The real, verified local URL a runtime (agents.schemas.Plan.run_command)
    # was actually confirmed reachable at — never set from an agent's own
    # claim, only from execution.docker.runtime.ManagedRuntime's own HTTP
    # readiness probe. None whenever no runtime was requested or requested
    # but never confirmed reachable.
    runtime_url: str | None = None
    runtime_status: Literal["starting", "running", "verification_failed", "start_failed", "stopped"] | None = None
    # Real browser (Playwright/Chromium) inspection of `runtime_url`, when
    # one was reachable — "none" whenever no runtime existed to inspect at
    # all (nothing to distinguish from a real check that ran), "unavailable"
    # when a runtime WAS reachable but the browser capability itself
    # couldn't run (Playwright/Chromium missing in this deployment — an
    # honest gap, never silently treated as passing), "browser" when a real
    # headless-Chromium page load actually happened. Reviewer/the UI must
    # never claim visual verification occurred unless this is "browser".
    visual_verification_kind: Literal["browser", "unavailable", "none"] = "none"
    # Only meaningful when visual_verification_kind == "browser": whether
    # the real rendered page showed genuine content (not blank, no broken
    # local images) — never set from an agent's own claim.
    visual_ok: bool | None = None
    visual_reason: str = ""
    console_errors: list[str] = Field(default_factory=list)
    # Workspace-relative path to a real screenshot Playwright captured of
    # the running application, or None if none was captured. Recorded as a
    # genuine execution artifact (see agents.graph's finalize node) so the
    # UI can show real proof of what was built, not merely a claim.
    screenshot_path: str | None = None


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
        # Phase 3 additions (static-site/runtime verification, see
        # agents.tester's static-site path and agents.failure_classification):
        # a referenced local asset (CSS/JS/image) is missing or not valid
        # binary content for its type, or the runtime process never became
        # reachable on its published port.
        "static_asset_error", "runtime_start_error",
        # Phase 8 addition: a runtime rendered but a real browser check found
        # it visibly blank/broken (see agents.failure_classification).
        "visual_quality_error",
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
