"""Centralized application settings, loaded from environment variables / .env."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
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
    # gemini (default) | qwen — provider-agnostic: swapping is a config
    # change (LLM_PROVIDER/LLM_MODEL/LLM_API_KEY/LLM_BASE_URL), not a code
    # change in any agent. LLM_BASE_URL only applies to OpenAI-compatible
    # providers (e.g. qwen) — Gemini uses Google's own endpoint.
    llm_provider: str = "gemini"
    llm_base_url: str = ""
    llm_model: str = "gemini-pro-latest"
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
    # Bounds on the LLM-driven tool-calling loop (Developer/Debugger): how
    # many tool calls one agent turn may make, how many an entire execution
    # may make in total across every agent turn, and a hard wall-clock cap
    # on the whole graph run. All exist so a malformed or adversarial
    # model response can never produce an unbounded autonomous loop.
    max_tool_calls_per_agent: int = 12
    max_total_tool_calls: int = 60
    max_execution_seconds: int = 900
    # Hard cap on total LangGraph node visits for one execution (LangGraph's
    # own `recursion_limit`) — the outer safety net beneath the debug-retry
    # budget: even a routing bug or a pathological state could not make the
    # graph loop forever, since LangGraph itself raises GraphRecursionError
    # once this is exceeded.
    max_agent_turns: int = 50
    # Character budget for RAG context handed to any single agent prompt.
    max_context_chars: int = 12_000

    # ---- Workspace intelligence (Phase 2.2) ----
    # Bounds on the Orchestrator's one-time repository structure scan
    # (`analysis.scanner.scan_repository`) — a large or deeply nested
    # workspace must never turn understanding it into an unbounded walk.
    workspace_scan_max_files: int = 2_000
    workspace_scan_max_depth: int = 8

    # ---- Logging ----
    log_level: str = "INFO"
    log_format: Literal["console", "json"] = "console"

    # ---- CORS ----
    cors_origins: str = "http://localhost:3000,http://localhost:5173"

    # ---- Workspace storage ----
    # Root directory for the default "LocoPilot Storage" workspace, used
    # whenever an execution is created without an explicit project or
    # workspace_path. Never hardcode a personal path here — if unset, a
    # platform-appropriate application-data directory is used instead.
    locopilot_workspace_root: str | None = None

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

    @property
    def workspace_root(self) -> Path:
        """The "LocoPilot Storage" root: `projects/`, `uploads/`,
        `executions/`, and `artifacts/` live under here. Configurable via
        LOCOPILOT_WORKSPACE_ROOT; otherwise a platform-appropriate
        application-data directory, never a path inside the repo or a
        hardcoded personal path."""
        if self.locopilot_workspace_root:
            root = Path(self.locopilot_workspace_root).expanduser()
        else:
            root = _default_app_data_dir() / "LocoPilot"
        for sub in ("projects", "uploads", "executions", "artifacts"):
            (root / sub).mkdir(parents=True, exist_ok=True)
        return root


def _default_app_data_dir() -> Path:
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
        if base:
            return Path(base)
        return Path.home() / "AppData" / "Local"
    xdg_data_home = os.environ.get("XDG_DATA_HOME")
    if xdg_data_home:
        return Path(xdg_data_home)
    if os.uname().sysname == "Darwin":  # noqa: SIM108 - explicit branch reads clearer than a ternary here
        return Path.home() / "Library" / "Application Support"
    return Path.home() / ".local" / "share"


@lru_cache
def get_settings() -> Settings:
    return Settings()
