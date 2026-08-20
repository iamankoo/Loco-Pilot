"""GET /api/v1/projects and GET /api/v1/projects/{id}.

Read-only — projects are currently created implicitly by
`POST /api/v1/executions` (see `executions.py`), not through a dedicated
creation endpoint here.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
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
from backend.app.db.repositories.projects import count_projects, get_project, list_projects
from backend.app.db.session import get_db
from backend.app.services.execution_detail import elapsed_seconds

router = APIRouter(prefix="/projects", tags=["projects"])


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
