"""Redis connection layer.

Phase 1.1 only needs connectivity + health check. The single async client
returned here is the intended attachment point for future execution
events (pub/sub), caching, queues, and cross-agent coordination — those
build on this client, not a parallel connection.
"""

from __future__ import annotations

from functools import lru_cache

import redis.asyncio as redis

from backend.app.core.config import get_settings
from backend.app.core.logging import get_logger

logger = get_logger(component="redis")


@lru_cache
def get_redis_client() -> redis.Redis:
    settings = get_settings()
    return redis.from_url(settings.redis_url, decode_responses=True)


async def check_redis() -> dict[str, str]:
    try:
        client = get_redis_client()
        pong = await client.ping()
        return {"status": "ok" if pong else "error"}
    except Exception as exc:  # noqa: BLE001 - health check must not raise
        logger.warning("redis_health_check_failed", error=str(exc))
        return {"status": "error", "detail": str(exc)}
