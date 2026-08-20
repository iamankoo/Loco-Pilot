from __future__ import annotations

from backend.app.core.config import Settings, get_settings


def test_settings_load_with_defaults() -> None:
    settings = Settings(_env_file=None)
    assert settings.app_env == "development"
    assert settings.api_port == 8000
    assert settings.llm_provider == "qwen"


def test_database_url_is_asyncpg() -> None:
    settings = Settings(_env_file=None)
    assert settings.database_url.startswith("postgresql+asyncpg://")


def test_redis_url_without_password() -> None:
    settings = Settings(_env_file=None, redis_password=None)
    assert settings.redis_url == f"redis://{settings.redis_host}:{settings.redis_port}/{settings.redis_db}"


def test_cors_origins_list_parses_csv() -> None:
    settings = Settings(_env_file=None, cors_origins="http://a.com, http://b.com")
    assert settings.cors_origins_list == ["http://a.com", "http://b.com"]


def test_get_settings_is_cached() -> None:
    assert get_settings() is get_settings()
