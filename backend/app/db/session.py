"""Async PostgreSQL engine/session management.

A single lazily-created async engine is reused for the process lifetime.
`get_db` is a FastAPI dependency that yields a scoped session per request;
future SQLAlchemy models attach to `Base` in `backend.app.db.base`.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from functools import lru_cache

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from backend.app.core.config import get_settings


@lru_cache
def get_engine() -> AsyncEngine:
    settings = get_settings()
    return create_async_engine(settings.database_url, pool_pre_ping=True, echo=False)


@lru_cache
def get_session_factory() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(get_engine(), expire_on_commit=False)


async def get_db() -> AsyncIterator[AsyncSession]:
    session_factory = get_session_factory()
    async with session_factory() as session:
        yield session
