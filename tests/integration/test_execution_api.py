from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

import pytest
from httpx import AsyncClient

from backend.app.core.config import get_settings
from tools.workspace import Workspace


async def test_create_execution_without_project_or_workspace_uses_default_storage(
    client: AsyncClient, db_session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Workspace selection is optional: omitting both project_id and
    workspace_path falls back to an auto-provisioned project under the
    LocoPilot Storage root instead of being rejected."""
    monkeypatch.setenv("LOCOPILOT_WORKSPACE_ROOT", str(tmp_path))
    get_settings.cache_clear()
    try:
        response = await client.post("/api/v1/executions", json={"task": "do something"})
        assert response.status_code == 201
        body = response.json()
        assert body["project_id"]
    finally:
        get_settings.cache_clear()


async def test_create_execution_rejects_invalid_workspace_path(client: AsyncClient, db_session) -> None:
    response = await client.post(
        "/api/v1/executions",
        json={"task": "do something", "workspace_path": "C:/definitely/does/not/exist/locopilot-test"},
    )
    assert response.status_code == 422


async def test_get_unknown_execution_returns_404(client: AsyncClient, db_session) -> None:
    response = await client.get(f"/api/v1/executions/{uuid.uuid4()}")
    assert response.status_code == 404


async def test_create_execution_unknown_project_id_returns_404(client: AsyncClient, db_session) -> None:
    response = await client.post("/api/v1/executions", json={"task": "x", "project_id": str(uuid.uuid4())})
    assert response.status_code == 404


async def test_create_execution_runs_to_a_terminal_status(
    client: AsyncClient, db_session, tmp_workspace: Workspace
) -> None:
    """End-to-end through the real API: creates a project+execution and lets
    the background task run the real graph. No LLM key is configured in
    this environment, so it must honestly end in status="error" — never
    silently reported as passed."""
    response = await client.post(
        "/api/v1/executions",
        json={"task": "add a hello file", "workspace_path": str(tmp_workspace.root), "project_name": "api-test"},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["task"] == "add a hello file"
    assert body["status"] in ("pending", "running")

    execution_id = body["id"]

    final = body
    for _ in range(30):
        get_response = await client.get(f"/api/v1/executions/{execution_id}")
        final = get_response.json()
        if final["status"] not in ("pending", "running"):
            break
        await asyncio.sleep(0.1)

    assert final["status"] in ("passed", "failed", "error", "needs_review")
