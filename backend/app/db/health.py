"""Database health check used by the readiness endpoint."""

from __future__ import annotations

from sqlalchemy import text

from backend.app.core.logging import get_logger
from backend.app.db.session import get_engine

logger = get_logger(component="db")


async def check_database() -> dict[str, str]:
    try:
        engine = get_engine()
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return {"status": "ok"}
    except Exception as exc:  # noqa: BLE001 - health check must not raise
        logger.warning("database_health_check_failed", error=str(exc))
        return {"status": "error", "detail": str(exc)}
