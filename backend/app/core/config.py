"""Centralized application settings, loaded from environment variables / .env."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ---- Application ----
    app_env: Literal["development", "test", "production"] = "development"
    api_host: str = "0.0.0.0"
    api_port: int = 8000

    # ---- PostgreSQL ----
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_user: str = "locopilot"
    postgres_password: str = "locopilot"
    postgres_db: str = "locopilot"

    # ---- Redis ----
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_db: int = 0
    redis_password: str | None = None

    # ---- LLM provider ----
    llm_provider: str = "qwen"
    llm_base_url: str = ""
    llm_model: str = "qwen3-coder-plus"
    llm_api_key: str | None = None
    llm_temperature: float = 0.2
    llm_request_timeout: int = 60

    # ---- Embedding provider ----
    # "hashing" (default) is a free, local, deterministic embedding used so
    # the RAG pipeline runs without any paid API. "openai_compatible" uses
    # an OpenAI-compatible embeddings endpoint (configurable, not tied to
    # any single vendor).
    embedding_provider: str = "hashing"
    embedding_base_url: str = ""
    embedding_model: str = "text-embedding-3-small"
    embedding_api_key: str | None = None
    # Fixed pgvector column width — the hashing provider always produces
    # this many dimensions; an OpenAI-compatible provider is asked to
    # truncate to this same width so the schema stays provider-agnostic.
    embedding_dimension: int = 384

    # ---- Agent execution ----
    max_debug_retries: int = 2

    # ---- Logging ----
    log_level: str = "INFO"
    log_format: Literal["console", "json"] = "console"

    # ---- CORS ----
    cors_origins: str = "http://localhost:3000,http://localhost:5173"

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def redis_url(self) -> str:
        auth = f":{self.redis_password}@" if self.redis_password else ""
        return f"redis://{auth}{self.redis_host}:{self.redis_port}/{self.redis_db}"

    @property
    def cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
