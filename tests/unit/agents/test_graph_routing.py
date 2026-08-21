from __future__ import annotations

from agents.graph import route_after_debugger, route_after_developer, route_after_planner, route_after_tester
from agents.schemas import TestResult
from agents.state import ExecutionState


def _state(**overrides) -> ExecutionState:
    defaults = dict(execution_id="1", project_id="2", user_task="x", workspace_root="C:/tmp")
    defaults.update(overrides)
    return ExecutionState(**defaults)


def test_route_after_planner_continues_normally() -> None:
    assert route_after_planner(_state(execution_status="developing")) == "developer"


def test_route_after_planner_finalizes_on_error() -> None:
    assert route_after_planner(_state(execution_status="error")) == "finalize"


def test_route_after_developer_continues_normally() -> None:
    assert route_after_developer(_state(execution_status="testing")) == "tester"


def test_route_after_developer_finalizes_on_error() -> None:
    assert route_after_developer(_state(execution_status="error")) == "finalize"


def test_route_after_tester_goes_to_debugger_when_failed_and_retries_remain() -> None:
    state = _state(test_results=TestResult(status="failed", summary="x"), retry_count=0)
    assert route_after_tester(state, max_retries=2) == "debugger"


def test_route_after_tester_goes_to_reviewer_when_passed() -> None:
    state = _state(test_results=TestResult(status="passed", summary="x"))
    assert route_after_tester(state, max_retries=2) == "reviewer"


def test_route_after_tester_goes_to_reviewer_when_unavailable() -> None:
    """Unavailable (no sandbox yet) is not a code failure — it must not
    trigger the debug loop, which exists to fix real bugs."""
    state = _state(test_results=TestResult(status="unavailable", summary="x"))
    assert route_after_tester(state, max_retries=2) == "reviewer"


def test_route_after_tester_stops_retrying_at_max_retries() -> None:
    state = _state(test_results=TestResult(status="failed", summary="x"), retry_count=2)
    assert route_after_tester(state, max_retries=2) == "reviewer"


def test_route_after_tester_never_exceeds_max_retries_regardless_of_repeated_failure() -> None:
    for retry_count in (2, 3, 10):
        state = _state(test_results=TestResult(status="failed", summary="x"), retry_count=retry_count)
        assert route_after_tester(state, max_retries=2) == "reviewer"


def test_route_after_tester_goes_to_debugger_when_timed_out_and_retries_remain() -> None:
    """A test command timing out is worth debugging too — it may be a
    real bug (e.g. an infinite loop) Developer just introduced."""
    state = _state(test_results=TestResult(status="timed_out", summary="x"), retry_count=0)
    assert route_after_tester(state, max_retries=2) == "debugger"


def test_route_after_tester_finalizes_on_error() -> None:
    state = _state(execution_status="error", test_results=TestResult(status="failed", summary="x"))
    assert route_after_tester(state, max_retries=2) == "finalize"


def test_route_after_debugger_continues_normally() -> None:
    assert route_after_debugger(_state(execution_status="developing")) == "developer"


def test_route_after_debugger_finalizes_on_error() -> None:
    assert route_after_debugger(_state(execution_status="error")) == "finalize"
