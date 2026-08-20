from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.models.project import Project


async def create_project(
    db: AsyncSession,
    *,
    name: str,
    repo_url: str | None = None,
    workspace_path: str | None = None,
) -> Project:
    project = Project(name=name, repo_url=repo_url, workspace_path=workspace_path)
    db.add(project)
    await db.commit()
    await db.refresh(project)
    return project


async def get_project(db: AsyncSession, project_id: uuid.UUID) -> Project | None:
    return await db.get(Project, project_id)
