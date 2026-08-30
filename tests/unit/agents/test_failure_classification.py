from __future__ import annotations

from agents.failure_classification import classify_failure
from agents.schemas import TestResult


def test_classifies_browser_verification_failure_as_visual_quality_error() -> None:
    result = TestResult(
        status="failed",
        summary="Static site check: entry point index.html — see errors.",
        errors=["Browser verification: Page appears blank or has too little visible text."],
        verification_kind="static_site",
        visual_verification_kind="browser",
        visual_ok=False,
    )
    assert classify_failure(result) == "visual_quality_error"


def test_visual_quality_error_is_distinct_from_static_asset_error() -> None:
    missing_asset_result = TestResult(
        status="failed",
        summary="Static site check — see errors.",
        errors=["Referenced local asset not found: hero.png"],
        verification_kind="static_site",
    )
    assert classify_failure(missing_asset_result) == "static_asset_error"
