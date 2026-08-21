"""The LangGraph state schema.

A typed Pydantic model, not a bare dict — every node reads/writes named,
validated fields. List fields use `Annotated[..., operator.add]` so nodes
append their own new items (a tool call, an error, a trace message) and
LangGraph concatenates them across the run, rather than every node needing
the full accumulated history just to add one entry.
"""

from __future__ import annotations

import operator
from typing import Annotated, Literal

from pydantic import BaseModel, Field

from agents.schemas import DebugResult, FileChange, Plan, ReviewResult, TestResult
from analysis.context import ProjectContext
from rag.retrieval.context_builder import RepositoryContext

ExecutionStatusLiteral = Literal[
    "pending",
    "planning",
    "developing",
    "testing",
    "debugging",
    "reviewing",
    "passed",
    "failed",
    "error",
    "cancelled",
    "timed_out",
    # An honest terminal state distinct from "passed": Reviewer approved
    # but the last real test run didn't actually pass, or the review-retry
    # budget was exhausted while changes were still requested — mirrors
    # the existing `ExecutionStatus.NEEDS_REVIEW` DB enum value (Phase
    # 1.6) at the graph-state level too.
    "needs_review",
]


class ToolCallRecord(BaseModel):
    tool_name: str
    status: Literal["success", "error"]
    duration_ms: int
    summary: str | None = None


class ExecutionState(BaseModel):
    execution_id: str
    project_id: str
    user_task: str
    workspace_root: str

    repository_context: RepositoryContext | None = None
    # Deterministic workspace/repository intelligence built once by the
    # Orchestrator (see `analysis.context.build_project_context`) — the
    # Planner reads this instead of relying on the LLM to "just know" the
    # repository. Never mutated after the Orchestrator's turn.
    project_context: ProjectContext | None = None
    plan: Plan | None = None
    current_agent: str | None = None

    messages: Annotated[list[str], operator.add] = Field(default_factory=list)
    tool_calls: Annotated[list[ToolCallRecord], operator.add] = Field(default_factory=list)
    files_changed: Annotated[list[FileChange], operator.add] = Field(default_factory=list)
    errors: Annotated[list[str], operator.add] = Field(default_factory=list)

    test_results: TestResult | None = None
    retry_count: int = 0
    # Debugger's most recent structured finding — explicit state so Developer
    # (and persistence/observability) can rely on it directly rather than
    # recovering it from the free-text `messages` trail. Last-write-wins,
    # like `plan`/`test_results`/`review_result`: only ever meaningful for
    # the retry cycle currently in progress.
    debug_result: DebugResult | None = None
    # The full debug-attempt history across every retry cycle, oldest
    # first — Debugger appends its own new attempt each turn; Tester's
    # subsequent turn patches the most recent entry's `status` to
    # "fixed"/"unresolved" once the real re-test result is known (see
    # `agents/tester.py`). A plain (not `operator.add`-accumulated) field,
    # like `plan`/`test_results`, because Tester's patch needs to replace
    # one existing entry, not just append.
    debug_attempts: list[DebugResult] = Field(default_factory=list)
    review_result: ReviewResult | None = None
    # How many times the review loop (Reviewer -> Developer -> Tester ->
    # Reviewer) has cycled — a separate counter from `retry_count` (the
    # debug loop's own), bounded independently by
    # `GraphDependencies.max_review_retries`.
    review_retry_count: int = 0
    # The full review history, oldest first, mirroring `debug_attempts`.
    review_attempts: list[ReviewResult] = Field(default_factory=list)
    final_result: dict | None = None
    execution_status: ExecutionStatusLiteral = "pending"


def compute_honest_status(state: ExecutionState) -> ExecutionStatusLiteral:
    """The single source of truth for whether an execution can honestly be
    reported as "passed": an "approved" review verdict is necessary but
    never sufficient — the last real test run must have actually passed
    too (Phase 2.1/2.8). Used identically by the graph's own finalize node
    (`agents.graph.make_finalize_node`) and the service layer's DB-status
    mapping (`backend.app.services.execution_service._map_final_status`),
    so the two representations of "did this execution succeed" can never
    disagree with each other.
    """
    if state.execution_status in ("error", "cancelled", "timed_out", "failed"):
        return state.execution_status
    if state.review_result is None:
        return "needs_review"
    tests_actually_passed = state.test_results is not None and state.test_results.status == "passed"
    if state.review_result.verdict == "approved" and tests_actually_passed:
        return "passed"
    return "needs_review"
