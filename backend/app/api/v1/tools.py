"""Read-only introspection of the tool registry.

Deliberately no execution endpoint here: tool execution is not exposed
over HTTP in Phase 1.2. A future execution API will call an execution
service, which calls tools internally — never the reverse.
"""

from __future__ import annotations

from fastapi import APIRouter

from tools.registry import build_default_registry

router = APIRouter(prefix="/tools", tags=["tools"])

_registry = build_default_registry()


@router.get("")
async def list_tools() -> list[dict]:
    return _registry.schemas()
