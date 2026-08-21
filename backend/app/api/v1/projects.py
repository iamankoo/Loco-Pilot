"""Project endpoints: list/detail (read), creation, workspace file
browsing, and file uploads.

Project creation and file browsing/upload all resolve to a project's
`workspace_path` and go through the same `Workspace` sandbox boundary
every agent tool uses — never an unrestricted filesystem path.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.api.v1.dashboard_schemas import (
    ExecutionSummary,
    ProjectDetailResponse,
    ProjectListResponse,
    ProjectSummary,
)
from backend.app.db.repositories.executions import (
    get_execution_status_counts_for_project,
    get_latest_execution_for_project,
    list_executions,
)
from backend.app.db.repositories.projects import count_projects, create_project, get_project, list_projects
from backend.app.db.session import get_db
from backend.app.services.execution_detail import elapsed_seconds
from backend.app.services.workspace_files import WorkspaceFileError, list_workspace_entries, save_uploaded_files
from backend.app.services.workspace_provisioning import provision_default_workspace
from tools.workspace import Workspace, WorkspaceError

router = APIRouter(prefix="/projects", tags=["projects"])


class CreateProjectRequest(BaseModel):
    name: str | None = None
    workspace_path: str | None = None


class WorkspaceEntryResponse(BaseModel):
    name: str
    path: str
    is_dir: bool
    size_bytes: int | None = None


class WorkspaceListResponse(BaseModel):
    path: str
    entries: list[WorkspaceEntryResponse]


class UploadedFileResponse(BaseModel):
    filename: str
    relative_path: str
    size_bytes: int
    content_type: str | None = None


class UploadResponse(BaseModel):
    files: list[UploadedFileResponse]


async def _project_summary(db: AsyncSession, project) -> ProjectSummary:
    latest = await get_latest_execution_for_project(db, project.id)
    counts = await get_execution_status_counts_for_project(db, project.id)
    return ProjectSummary(
        id=project.id,
        name=project.name,
        repo_url=project.repo_url,
        workspace_path=project.workspace_path,
        created_at=project.created_at,
        updated_at=project.updated_at,
        last_execution_status=latest.status if latest else None,
        last_execution_at=latest.created_at if latest else None,
        execution_counts=counts,
    )


@router.get("", response_model=ProjectListResponse)
async def list_projects_endpoint(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> ProjectListResponse:
    projects = await list_projects(db, limit=limit, offset=offset)
    total = await count_projects(db)
    items = [await _project_summary(db, project) for project in projects]
    return ProjectListResponse(items=items, total=total, limit=limit, offset=offset)


@router.get("/{project_id}", response_model=ProjectDetailResponse)
async def get_project_endpoint(project_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> ProjectDetailResponse:
    project = await get_project(db, project_id)
    if project is None:
        raise HTTPException(404, "Project not found.")

    summary = await _project_summary(db, project)
    recent = await list_executions(db, project_id=project_id, limit=10, offset=0)
    recent_summaries = [
        ExecutionSummary(
            id=e.id,
            project_id=e.project_id,
            project_name=project.name,
            task=e.task,
            status=e.status,
            current_agent=e.current_agent,
            error_message=e.error_message,
            created_at=e.created_at,
            started_at=e.started_at,
            completed_at=e.completed_at,
            elapsed_seconds=elapsed_seconds(e.started_at, e.completed_at),
        )
        for e in recent
    ]

    return ProjectDetailResponse(**summary.model_dump(), recent_executions=recent_summaries)


@router.post("", status_code=201, response_model=ProjectSummary)
async def create_project_endpoint(
    payload: CreateProjectRequest, db: AsyncSession = Depends(get_db)
) -> ProjectSummary:
    """Resolves or provisions a workspace and registers a project for it.
    Used by the frontend's workspace selector before uploading files or
    running an execution — separate from `POST /executions`, which still
    creates a project implicitly for the no-attachment case."""
    workspace_path = payload.workspace_path
    name = payload.name
    if not workspace_path:
        name, workspace_path = provision_default_workspace(
            seed_text=payload.name or "project", project_name=payload.name
        )
    else:
        try:
            Workspace.at(workspace_path)
        except WorkspaceError as exc:
            raise HTTPException(422, f"Invalid workspace_path: {exc}") from exc

    project = await create_project(db, name=name or workspace_path, workspace_path=workspace_path)
    return await _project_summary(db, project)


@router.get("/{project_id}/files", response_model=WorkspaceListResponse)
async def list_project_files_endpoint(
    project_id: uuid.UUID,
    path: str = Query("", description="Workspace-relative directory path; empty for the workspace root."),
    db: AsyncSession = Depends(get_db),
) -> WorkspaceListResponse:
    project = await get_project(db, project_id)
    if project is None:
        raise HTTPException(404, "Project not found.")

    try:
        entries = list_workspace_entries(project.workspace_path, path)
    except WorkspaceFileError as exc:
        raise HTTPException(422, str(exc)) from exc

    return WorkspaceListResponse(
        path=path,
        entries=[
            WorkspaceEntryResponse(name=e.name, path=e.path, is_dir=e.is_dir, size_bytes=e.size_bytes)
            for e in entries
        ],
    )


@router.post("/{project_id}/uploads", status_code=201, response_model=UploadResponse)
async def upload_project_files_endpoint(
    project_id: uuid.UUID, files: list[UploadFile] = File(...), db: AsyncSession = Depends(get_db)
) -> UploadResponse:
    project = await get_project(db, project_id)
    if project is None:
        raise HTTPException(404, "Project not found.")

    try:
        saved = await save_uploaded_files(project.workspace_path, files)
    except WorkspaceFileError as exc:
        raise HTTPException(422, str(exc)) from exc

    return UploadResponse(
        files=[
            UploadedFileResponse(
                filename=f.filename, relative_path=f.relative_path, size_bytes=f.size_bytes, content_type=f.content_type
            )
            for f in saved
        ]
    )
