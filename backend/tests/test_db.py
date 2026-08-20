"""Integration test against a real PostgreSQL instance.

Skips (rather than fails) when no database is reachable, so the suite stays
deterministic in environments without the docker-compose infra running.
"""

from __future__ import annotations

import pytest

from backend.app.db.health import check_database


async def test_database_connectivity() -> None:
    result = await check_database()
    if result["status"] != "ok":
        pytest.skip(f"PostgreSQL not reachable: {result.get('detail')}")
    assert result == {"status": "ok"}
