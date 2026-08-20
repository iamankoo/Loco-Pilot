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


def test_developer_plan_defaults_empty() -> None:
    plan = DeveloperPlan(summary="no-op")
    assert plan.edits == []
    assert plan.writes == []


def test_file_change_rejects_invalid_change_type() -> None:
    with pytest.raises(ValidationError):
        FileChange(path="a.py", change_type="deleted", detail="x")  # not a valid literal


def test_test_result_rejects_invalid_status() -> None:
    with pytest.raises(ValidationError):
        TestResult(status="maybe", summary="x")


def test_debug_result_rejects_invalid_confidence() -> None:
    with pytest.raises(ValidationError):
        DebugResult(root_cause="x", proposed_fix="y", confidence="certain")


def test_review_result_rejects_invalid_verdict() -> None:
    with pytest.raises(ValidationError):
        ReviewResult(verdict="looks_fine", summary="x")


def test_review_result_valid_verdicts() -> None:
    assert ReviewResult(verdict="approved", summary="x").verdict == "approved"
    assert ReviewResult(verdict="changes_required", summary="x").verdict == "changes_required"
