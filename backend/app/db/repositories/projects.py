from __future__ import annotations

import uuid

from sqlalchemy import func, select
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


async def list_projects(db: AsyncSession, *, limit: int = 20, offset: int = 0) -> list[Project]:
    stmt = select(Project).order_by(Project.created_at.desc()).limit(limit).offset(offset)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def count_projects(db: AsyncSession) -> int:
    result = await db.execute(select(func.count()).select_from(Project))
    return result.scalar_one()
