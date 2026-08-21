"""Phase 2.12: one error-classification taxonomy for execution
observability — extends, rather than duplicates, the LLM status
distinctions `backend.app.services.llm_health._classify_error` already
established (not_configured / auth_failed / model_access_denied) with the
additional codes non-LLM execution failures need. Deterministic
substring matching over a real error message, same style as
`llm_health.py`'s own classifier — never an LLM's own guess at why it
failed.
"""

from __future__ import annotations

ERROR_CODES = frozenset(
    {
        "llm_configuration_error",
        "llm_auth_error",
        "llm_quota_error",
        "llm_model_access_error",
        "tool_error",
        "test_failure",
        "timeout",
        "workspace_error",
        "git_error",
        "review_failure",
        "graph_recursion_limit",
        "cancellation",
        "unknown_error",
    }
)


def classify_error(message: str | None) -> str:
    if not message:
        return "unknown_error"
    lowered = message.lower()

    if "cancel" in lowered:
        return "cancellation"
    if "recursion" in lowered or "agent turns" in lowered:
        return "graph_recursion_limit"
    if "time limit" in lowered or "timed out" in lowered or "timeout" in lowered:
        return "timeout"
    if "not configured" in lowered and ("api_key" in lowered or "llm" in lowered):
        return "llm_configuration_error"
    if (
        "401" in message
        or "incorrect api key" in lowered
        or "invalid_api_key" in lowered
        or "authenticationerror" in lowered
    ):
        return "llm_auth_error"
    # Same "limit: 0" distinction llm_health.py draws: a real transient
    # rate limit (llm_quota_error) is a different problem from a zero-quota
    # entitlement gap on the provider account (llm_model_access_error).
    if (
        "unpurchased" in lowered
        or "accessdenied" in lowered
        or "permissiondenied" in lowered
        or "403" in message
        or "resourceexhausted" in lowered
        or ("quota" in lowered and "limit: 0" in lowered)
    ):
        return "llm_model_access_error"
    if "quota" in lowered or "429" in message or "rate limit" in lowered:
        return "llm_quota_error"
    if "workspace" in lowered and ("outside" in lowered or "invalid" in lowered or "traversal" in lowered):
        return "workspace_error"
    if lowered.startswith("git ") or "git diff failed" in lowered or "git status failed" in lowered:
        return "git_error"
    if "test" in lowered and ("failed" in lowered or "failing" in lowered):
        return "test_failure"
    if "review" in lowered and "changes" in lowered:
        return "review_failure"
    if "tool" in lowered:
        return "tool_error"
    return "unknown_error"
