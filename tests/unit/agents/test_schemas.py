from __future__ import annotations

import pytest
from pydantic import ValidationError

from agents.schemas import DebugResult, DeveloperPlan, FileChange, Plan, ReviewResult, TestResult


def test_plan_requires_steps() -> None:
    with pytest.raises(ValidationError):
        Plan(objective="do something", testing_strategy="run tests")  # missing required 'steps'


def test_plan_defaults() -> None:
    plan = Plan(objective="x", steps=["a"], testing_strategy="run tests")
    assert plan.assumptions == []
    assert plan.files_likely_involved == []
    assert plan.risks == []
    assert plan.expected_artifact_glob is None


def test_developer_plan_requires_summary() -> None:
    with pytest.raises(ValidationError):
        DeveloperPlan()
    assert DeveloperPlan(summary="no-op").summary == "no-op"


def test_file_change_rejects_invalid_change_type() -> None:
    with pytest.raises(ValidationError):
        FileChange(path="a.py", change_type="renamed_to_somewhere", detail="x")  # not a valid literal


def test_file_change_accepts_deleted_and_renamed() -> None:
    # Phase 2.3 added delete_file/move_file tool support alongside the
    # original write_file/edit_file-only change types.
    assert FileChange(path="a.py", change_type="deleted", detail="x").change_type == "deleted"
    assert FileChange(path="a.py", change_type="renamed", detail="x").change_type == "renamed"


def test_test_result_rejects_invalid_status() -> None:
    with pytest.raises(ValidationError):
        TestResult(status="maybe", summary="x")


def test_debug_result_rejects_invalid_confidence() -> None:
    with pytest.raises(ValidationError):
        DebugResult(root_cause="x", proposed_fix="y", confidence="certain")


def test_debug_result_accepts_visual_quality_error_failure_class() -> None:
    result = DebugResult(
        root_cause="x", proposed_fix="y", confidence="medium", failure_class="visual_quality_error"
    )
    assert result.failure_class == "visual_quality_error"


def test_test_result_visual_verification_fields_default_to_honest_none() -> None:
    """A TestResult built without any visual-verification-specific
    argument (e.g. a conventional pytest/Jest run) must never silently
    imply a browser check happened."""
    result = TestResult(status="passed", summary="3 passed")
    assert result.visual_verification_kind == "none"
    assert result.visual_ok is None
    assert result.console_errors == []
    assert result.screenshot_path is None


def test_review_result_rejects_invalid_verdict() -> None:
    with pytest.raises(ValidationError):
        ReviewResult(verdict="looks_fine", summary="x")


def test_review_result_valid_verdicts() -> None:
    assert ReviewResult(verdict="approved", summary="x").verdict == "approved"
    assert ReviewResult(verdict="changes_required", summary="x").verdict == "changes_required"
