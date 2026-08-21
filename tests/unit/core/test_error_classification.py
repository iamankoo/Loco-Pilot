from __future__ import annotations

from backend.app.core.error_classification import classify_error


def test_classifies_llm_configuration_error() -> None:
    assert classify_error("LLM_API_KEY is not configured.") == "llm_configuration_error"


def test_classifies_llm_auth_error() -> None:
    assert classify_error("401 Incorrect API key provided") == "llm_auth_error"


def test_classifies_llm_model_access_error_for_zero_quota_entitlement() -> None:
    message = "429 You exceeded your current quota... limit: 0, model: gemini-pro"
    assert classify_error(message) == "llm_model_access_error"


def test_classifies_llm_quota_error_for_a_real_rate_limit() -> None:
    assert classify_error("429 Too Many Requests: rate limit exceeded, retry in 5s") == "llm_quota_error"


def test_classifies_timeout() -> None:
    assert classify_error("Execution exceeded the 600s time limit.") == "timeout"


def test_classifies_graph_recursion_limit() -> None:
    assert classify_error("Execution exceeded the maximum of 40 agent turns.") == "graph_recursion_limit"


def test_classifies_cancellation() -> None:
    assert classify_error("Execution was cancelled by request.") == "cancellation"


def test_classifies_workspace_error() -> None:
    assert classify_error("Path escapes workspace boundary: invalid traversal detected") == "workspace_error"


def test_classifies_git_error() -> None:
    assert classify_error("git diff failed: fatal: not a git repository") == "git_error"


def test_unknown_message_falls_back_to_unknown_error() -> None:
    assert classify_error("something entirely unexpected happened") == "unknown_error"


def test_none_message_is_unknown_error() -> None:
    assert classify_error(None) == "unknown_error"
