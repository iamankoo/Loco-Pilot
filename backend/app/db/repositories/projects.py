from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.models.project import Project


async def find_project_by_name(db: AsyncSession, name: str) -> Project | None:
    """Case-insensitive lookup used by workspace discovery to find an
    already-registered project by name before ever provisioning a new
    directory — an exact match wins; otherwise the most recently created
    project whose name contains (or is contained by) the query."""
    normalized = name.strip().lower()
    if not normalized:
        return None

    exact = await db.execute(select(Project).where(func.lower(Project.name) == normalized))
    match = exact.scalars().first()
    if match is not None:
        return match

    stmt = select(Project).order_by(Project.created_at.desc())
    result = await db.execute(stmt)
    for project in result.scalars().all():
        lowered = project.name.strip().lower()
        if normalized in lowered or lowered in normalized:
            return project
    return None


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
