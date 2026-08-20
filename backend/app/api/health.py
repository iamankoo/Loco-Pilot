"""Unversioned liveness/readiness endpoints.

These live outside `/api/v1` because infra (load balancers, container
orchestrators) conventionally probe a stable, unversioned `/health` path.
"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from backend.app.db.health import check_database
from backend.app.services.redis_service import check_redis

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict[str, str]:
    """Liveness: the process is up. Does not touch dependencies."""
    return {"status": "ok", "service": "locopilot-api", "version": "0.1.0"}


@router.get("/health/ready")
async def readiness() -> JSONResponse:
    """Readiness: the process and its required dependencies are usable."""
    database_status = await check_database()
    redis_status = await check_redis()

    checks = {"database": database_status, "redis": redis_status}
    healthy = all(check["status"] == "ok" for check in checks.values())

    return JSONResponse(
        status_code=200 if healthy else 503,
        content={"status": "ok" if healthy else "error", "checks": checks},
    )
