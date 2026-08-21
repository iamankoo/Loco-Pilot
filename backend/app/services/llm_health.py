"""LLM (Qwen/OpenAI-compatible) connectivity status for the settings UI.

Distinguishes three states that a single "configured or not" flag would
conflate:

- ``not_configured``: no base URL / API key set at all.
- ``auth_failed``: credentials are present but rejected outright (bad key).
- ``model_access_denied``: the key authenticates, but the account has no
  purchased/activated access to the configured model — this is an
  account/entitlement problem on the provider's console, not a LocoPilot
  bug, and must never be reported as "not configured".
- ``ok``: a real completion request succeeded.

A live probe call costs a real API request, so the result is cached
briefly rather than re-checked on every poll from the settings page.
"""

from __future__ import annotations

import time

from backend.app.core.config import Settings, get_settings
from backend.app.core.errors import LLMConfigurationError
from backend.app.core.llm.factory import build_llm_provider

_CACHE_TTL_SECONDS = 45.0
_cache: dict[str, object] = {}


def _classify_error(message: str) -> tuple[str, str]:
    lowered = message.lower()
    if "401" in message or "incorrect api key" in lowered or "invalid_api_key" in lowered or "authenticationerror" in lowered:
        return "auth_failed", message
    # Covers both the OpenAI-compatible shape (Qwen: "AccessDenied.Unpurchased",
    # 403) and Google's shape (Gemini: "PermissionDenied", 403, or a
    # ResourceExhausted/429 quota with limit 0 — a free-tier model
    # entitlement gap, not a transient rate limit).
    if (
        "unpurchased" in lowered
        or "accessdenied" in lowered
        or "permissiondenied" in lowered
        or "403" in message
        or "resourceexhausted" in lowered
        or ("quota" in lowered and "limit: 0" in lowered)
    ):
        return "model_access_denied", message
    return "error", message


async def _probe(settings: Settings) -> dict[str, object]:
    if not settings.llm_base_url or not settings.llm_api_key:
        return {
            "status": "not_configured",
            "provider": settings.llm_provider,
            "model": settings.llm_model,
            "detail": "Qwen Coder is not configured. Set LLM_API_KEY (and LLM_BASE_URL) in the backend environment.",
        }

    try:
        chat_model = build_llm_provider(settings).chat_model()
    except LLMConfigurationError as exc:
        return {
            "status": "not_configured",
            "provider": settings.llm_provider,
            "model": settings.llm_model,
            "detail": str(exc),
        }

    try:
        await chat_model.ainvoke("Reply with exactly one word: pong")
    except Exception as exc:  # noqa: BLE001 - any provider/transport failure is a status to report, not a crash
        message = str(exc)
        if settings.llm_api_key:
            message = message.replace(settings.llm_api_key, "<redacted>")
        status, detail = _classify_error(message)
        return {"status": status, "provider": settings.llm_provider, "model": settings.llm_model, "detail": detail}

    return {"status": "ok", "provider": settings.llm_provider, "model": settings.llm_model, "detail": None}


async def check_llm_status(*, force: bool = False) -> dict[str, object]:
    now = time.monotonic()
    cached = _cache.get("result")
    cached_at = _cache.get("at")
    if not force and cached is not None and cached_at is not None and now - cached_at < _CACHE_TTL_SECONDS:  # type: ignore[operator]
        return cached  # type: ignore[return-value]

    result = await _probe(get_settings())
    _cache["result"] = result
    _cache["at"] = now
    return result
