"""Aggregate router for the /api/v1 surface.

Empty of feature routes in Phase 1.1 by design (no agent/task endpoints
yet) — later milestones (executions, agents, RAG) register their routers
here without changing how /api/v1 is mounted in `backend.app.main`.
"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()


@router.get("/")
async def api_v1_info() -> dict[str, str]:
    return {"api_version": "v1", "status": "ok"}
