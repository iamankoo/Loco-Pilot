"""Integration test against a real Redis instance.

Skips (rather than fails) when no Redis is reachable, so the suite stays
deterministic in environments without the docker-compose infra running.
"""

from __future__ import annotations

import pytest

from backend.app.services.redis_service import check_redis


async def test_redis_connectivity() -> None:
    result = await check_redis()
    if result["status"] != "ok":
        pytest.skip(f"Redis not reachable: {result.get('detail')}")
    assert result == {"status": "ok"}
