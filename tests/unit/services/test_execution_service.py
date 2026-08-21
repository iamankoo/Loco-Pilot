"""`_map_final_status`: the graph's own `execution_status` field is
enough for cancellation/timeout/error, but a "passed" report additionally
requires the graph to have actually observed a passing test run — an
"approved" Reviewer verdict is necessary but never sufficient on its own,
since the LLM's judgement is not a substitute for the real test outcome.
"""

from __future__ import annotations

from agents.schemas import ReviewResult, TestResult
from agents.state import ExecutionState
from backend.app.db.models.execution import ExecutionStatus
from backend.app.services.execution_service import _map_final_status


def _base_state(**overrides) -> ExecutionState:
    defaults = dict(
        execution_id="11111111-1111-1111-1111-111111111111",
        project_id="22222222-2222-2222-2222-222222222222",
        user_task="do something",
        workspace_root="C:/tmp/does-not-matter",
    )
    defaults.update(overrides)
    return ExecutionState(**defaults)


def test_maps_cancelled_and_timed_out_and_error_directly() -> None:
    assert _map_final_status(_base_state(execution_status="cancelled")) == ExecutionStatus.CANCELLED
    assert _map_final_status(_base_state(execution_status="timed_out")) == ExecutionStatus.TIMED_OUT
    assert _map_final_status(_base_state(execution_status="error")) == ExecutionStatus.ERROR


def test_needs_review_when_reviewer_never_ran() -> None:
    state = _base_state(execution_status="reviewing", review_result=None)
    assert _map_final_status(state) == ExecutionStatus.NEEDS_REVIEW


def test_passed_requires_both_approval_and_a_real_passing_test_run() -> None:
    state = _base_state(
        execution_status="passed",
        review_result=ReviewResult(verdict="approved", summary="looks fine"),
        test_results=TestResult(status="passed", summary="all green"),
    )
    assert _map_final_status(state) == ExecutionStatus.PASSED


def test_approved_verdict_is_not_enough_if_tests_actually_failed() -> None:
    """The core Phase 2.1 fix: the graph, not the Reviewer's own
    judgement, owns whether a run can be honestly reported as passed."""
    state = _base_state(
        execution_status="passed",
        review_result=ReviewResult(verdict="approved", summary="looks fine to me"),
        test_results=TestResult(status="failed", summary="1 failed"),
    )
    assert _map_final_status(state) == ExecutionStatus.NEEDS_REVIEW


def test_approved_verdict_is_not_enough_if_tests_never_ran() -> None:
    state = _base_state(
        execution_status="passed",
        review_result=ReviewResult(verdict="approved", summary="looks fine"),
        test_results=None,
    )
    assert _map_final_status(state) == ExecutionStatus.NEEDS_REVIEW


def test_changes_required_verdict_is_needs_review_even_with_passing_tests() -> None:
    state = _base_state(
        execution_status="passed",
        review_result=ReviewResult(verdict="changes_required", summary="needs more work"),
        test_results=TestResult(status="passed", summary="all green"),
    )
    assert _map_final_status(state) == ExecutionStatus.NEEDS_REVIEW
