"""Aggregate router for the /api/v1 surface.

Later milestones (executions, agents, RAG) register their routers here
without changing how /api/v1 is mounted in `backend.app.main`.
"""

from __future__ import annotations

from fastapi import APIRouter

from backend.app.api.v1.executions import router as executions_router
from backend.app.api.v1.tools import router as tools_router

router = APIRouter()
router.include_router(tools_router)
router.include_router(executions_router)


@router.get("/")
async def api_v1_info() -> dict[str, str]:
    return {"api_version": "v1", "status": "ok"}
