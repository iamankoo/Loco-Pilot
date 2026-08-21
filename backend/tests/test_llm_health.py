from __future__ import annotations

import pytest

from backend.app.core.config import Settings
from backend.app.services import llm_health


@pytest.fixture(autouse=True)
def _clear_cache():
    llm_health._cache.clear()
    yield
    llm_health._cache.clear()


async def test_not_configured_when_key_missing() -> None:
    settings = Settings(_env_file=None, llm_base_url="", llm_api_key=None)
    result = await llm_health._probe(settings)
    assert result["status"] == "not_configured"
    assert "LLM_API_KEY" in result["detail"]


def test_classifies_auth_failure() -> None:
    status, _ = llm_health._classify_error(
        "Error code: 401 - {'error': {'message': 'Incorrect API key provided', 'code': 'invalid_api_key'}}"
    )
    assert status == "auth_failed"


def test_classifies_model_access_denied() -> None:
    status, _ = llm_health._classify_error(
        "Error code: 403 - {'error': {'message': 'Access to model denied.', 'code': 'AccessDenied.Unpurchased'}}"
    )
    assert status == "model_access_denied"


def test_classifies_gemini_permission_denied_as_model_access_denied() -> None:
    status, _ = llm_health._classify_error("PermissionDenied: 403 Your project has been denied access.")
    assert status == "model_access_denied"


def test_classifies_gemini_zero_quota_as_model_access_denied() -> None:
    status, _ = llm_health._classify_error(
        "ResourceExhausted: 429 You exceeded your current quota. "
        "Quota exceeded for metric: generate_content_free_tier_requests, limit: 0, model: gemini-3.1-pro"
    )
    assert status == "model_access_denied"


def test_classifies_unknown_error_generically() -> None:
    status, _ = llm_health._classify_error("Error code: 500 - Internal Server Error")
    assert status == "error"


async def test_never_exposes_api_key_in_result(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(
        _env_file=None,
        llm_base_url="https://example.invalid/v1",
        llm_api_key="super-secret-key-value",
        llm_model="qwen3-coder-plus",
    )

    class _FakeChatModel:
        async def ainvoke(self, _prompt: str) -> None:
            raise RuntimeError("Error code: 403 - AccessDenied.Unpurchased (key=super-secret-key-value)")

    class _FakeProvider:
        def chat_model(self) -> _FakeChatModel:
            return _FakeChatModel()

    monkeypatch.setattr(llm_health, "build_llm_provider", lambda _settings: _FakeProvider())
    result = await llm_health._probe(settings)
    assert result["status"] == "model_access_denied"
    assert "super-secret-key-value" not in str(result)


async def test_check_llm_status_caches_result(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"count": 0}

    async def fake_probe(_settings):
        calls["count"] += 1
        return {"status": "ok", "provider": "qwen", "model": "qwen3-coder-plus", "detail": None}

    monkeypatch.setattr(llm_health, "_probe", fake_probe)
    first = await llm_health.check_llm_status()
    second = await llm_health.check_llm_status()
    assert first == second
    assert calls["count"] == 1

    third = await llm_health.check_llm_status(force=True)
    assert calls["count"] == 2
    assert third["status"] == "ok"
