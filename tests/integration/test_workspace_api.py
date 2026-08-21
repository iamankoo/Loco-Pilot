"""Tests for POST /projects, GET /projects/{id}/files, and
POST /projects/{id}/uploads — project/workspace provisioning and safe,
workspace-bounded file browsing and upload.
"""

from __future__ import annotations

import io
import uuid
from pathlib import Path

import pytest
from httpx import AsyncClient

from backend.app.core.config import get_settings
from backend.app.db.repositories.projects import create_project


async def test_create_project_with_explicit_workspace_path(client: AsyncClient, tmp_path: Path) -> None:
    response = await client.post(
        "/api/v1/projects", json={"name": "explicit-workspace", "workspace_path": str(tmp_path)}
    )
    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "explicit-workspace"
    assert body["workspace_path"] == str(tmp_path)


async def test_create_project_rejects_nonexistent_workspace_path(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/projects", json={"name": "bad", "workspace_path": "/definitely/does/not/exist"}
    )
    assert response.status_code == 422


async def test_create_project_without_workspace_path_uses_default_storage(
    client: AsyncClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LOCOPILOT_WORKSPACE_ROOT", str(tmp_path))
    get_settings.cache_clear()
    try:
        response = await client.post("/api/v1/projects", json={"name": "auto-provisioned"})
        assert response.status_code == 201
        body = response.json()
        assert body["workspace_path"]
        assert Path(body["workspace_path"]).is_dir()
        assert Path(body["workspace_path"]).parent == tmp_path / "projects"
    finally:
        get_settings.cache_clear()


async def test_list_project_files_returns_workspace_contents(
    client: AsyncClient, db_session, tmp_path: Path
) -> None:
    (tmp_path / "main.py").write_text("print('hi')")
    project = await create_project(db_session, name=f"proj-{uuid.uuid4()}", workspace_path=str(tmp_path))

    response = await client.get(f"/api/v1/projects/{project.id}/files")
    assert response.status_code == 200
    names = {e["name"] for e in response.json()["entries"]}
    assert "main.py" in names


async def test_list_project_files_rejects_path_traversal(client: AsyncClient, db_session, tmp_path: Path) -> None:
    project = await create_project(db_session, name=f"proj-{uuid.uuid4()}", workspace_path=str(tmp_path))

    response = await client.get(f"/api/v1/projects/{project.id}/files", params={"path": "../../../etc"})
    assert response.status_code == 422


async def test_list_project_files_404_for_unknown_project(client: AsyncClient) -> None:
    response = await client.get(f"/api/v1/projects/{uuid.uuid4()}/files")
    assert response.status_code == 404


async def test_upload_file_lands_inside_project_workspace(
    client: AsyncClient, db_session, tmp_path: Path
) -> None:
    project = await create_project(db_session, name=f"proj-{uuid.uuid4()}", workspace_path=str(tmp_path))

    response = await client.post(
        f"/api/v1/projects/{project.id}/uploads",
        files={"files": ("notes.md", io.BytesIO(b"# hello"), "text/markdown")},
    )
    assert response.status_code == 201
    body = response.json()["files"][0]
    assert body["relative_path"] == "uploads/notes.md"
    assert (tmp_path / "uploads" / "notes.md").read_text() == "# hello"


async def test_upload_rejects_disallowed_extension(client: AsyncClient, db_session, tmp_path: Path) -> None:
    project = await create_project(db_session, name=f"proj-{uuid.uuid4()}", workspace_path=str(tmp_path))

    response = await client.post(
        f"/api/v1/projects/{project.id}/uploads",
        files={"files": ("payload.exe", io.BytesIO(b"MZ"), "application/octet-stream")},
    )
    assert response.status_code == 422
    assert not any((tmp_path / "uploads").glob("*")) if (tmp_path / "uploads").exists() else True


async def test_upload_404_for_unknown_project(client: AsyncClient) -> None:
    response = await client.post(
        f"/api/v1/projects/{uuid.uuid4()}/uploads",
        files={"files": ("a.py", io.BytesIO(b"x"), "text/x-python")},
    )
    assert response.status_code == 404
