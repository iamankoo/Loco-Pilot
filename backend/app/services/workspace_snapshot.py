"""Durable copies of a project's workspace files (see db/models/project_file.py).

Taken after every execution; used to (a) serve the file listing/downloads when
the server's disk has been wiped, and (b) rebuild the workspace directory
before a later execution needs it.
"""

from __future__ import annotations

import uuid
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.logging import get_logger
from backend.app.db.models.project_file import ProjectFile
from backend.app.services.workspace_files import (
    MAX_TREE_FILES,
    WorkspaceEntry,
    WorkspaceFileError,
    list_workspace_tree,
    read_workspace_file,
)
from tools.workspace import Workspace, WorkspaceError

logger = get_logger(component="workspace_snapshot")

MAX_SNAPSHOT_FILE_BYTES = 2_000_000
MAX_SNAPSHOT_TOTAL_BYTES = 30_000_000


def workspace_exists(workspace_path: str | None) -> bool:
    return bool(workspace_path) and Path(workspace_path).is_dir()


async def snapshot_workspace(db: AsyncSession, project_id: uuid.UUID, workspace_path: str | None) -> int:
    """Replaces the project's stored copy with the workspace's current files.
    Returns the number of files stored. A missing workspace leaves the
    existing snapshot untouched (it may be the only copy left)."""
    if not workspace_exists(workspace_path):
        return 0
    try:
        entries, _truncated = list_workspace_tree(workspace_path)
    except WorkspaceFileError as exc:
        logger.warning("snapshot_skipped", reason=str(exc))
        return 0

    rows: list[ProjectFile] = []
    total = 0
    for entry in entries:
        if entry.size_bytes is None or entry.size_bytes > MAX_SNAPSHOT_FILE_BYTES:
            continue
        if total + entry.size_bytes > MAX_SNAPSHOT_TOTAL_BYTES:
            logger.warning("snapshot_total_cap_reached", stored=len(rows))
            break
        try:
            data = read_workspace_file(workspace_path, entry.path).read_bytes()
        except (WorkspaceFileError, OSError):
            continue
        total += len(data)
        rows.append(ProjectFile(project_id=project_id, path=entry.path, size_bytes=len(data), content=data))

    await db.execute(delete(ProjectFile).where(ProjectFile.project_id == project_id))
    db.add_all(rows)
    await db.commit()
    logger.info("workspace_snapshot_saved", project_id=str(project_id), files=len(rows), bytes=total)
    return len(rows)


async def list_snapshot(db: AsyncSession, project_id: uuid.UUID) -> tuple[list[WorkspaceEntry], bool]:
    result = await db.execute(
        select(ProjectFile.path, ProjectFile.size_bytes)
        .where(ProjectFile.project_id == project_id)
        .order_by(ProjectFile.path)
    )
    entries = [
        WorkspaceEntry(name=path.rsplit("/", 1)[-1], path=path, is_dir=False, size_bytes=size)
        for path, size in result.all()
    ]
    return entries[:MAX_TREE_FILES], len(entries) > MAX_TREE_FILES


async def read_snapshot_file(db: AsyncSession, project_id: uuid.UUID, path: str) -> bytes | None:
    # Same path rules as the live workspace: relative, no traversal, nothing hidden.
    parts = Path(path).parts
    if not path or Path(path).is_absolute() or ".." in parts or any(p.startswith(".") for p in parts):
        return None
    result = await db.execute(
        select(ProjectFile.content).where(ProjectFile.project_id == project_id, ProjectFile.path == path)
    )
    return result.scalar_one_or_none()


async def restore_workspace(db: AsyncSession, project_id: uuid.UUID, workspace_path: str | None) -> int:
    """Recreates a wiped workspace directory from the stored copy. No-op if
    the directory already exists or nothing was stored."""
    if not workspace_path or workspace_exists(workspace_path):
        return 0
    result = await db.execute(
        select(ProjectFile.path, ProjectFile.content).where(ProjectFile.project_id == project_id)
    )
    rows = result.all()
    root = Path(workspace_path)
    root.mkdir(parents=True, exist_ok=True)
    try:
        workspace = Workspace.at(root)
    except WorkspaceError:
        return 0
    restored = 0
    for path, content in rows:
        try:
            target = workspace.resolve(path)
        except WorkspaceError:
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        restored += 1
    logger.info("workspace_restored", project_id=str(project_id), files=restored)
    return restored
