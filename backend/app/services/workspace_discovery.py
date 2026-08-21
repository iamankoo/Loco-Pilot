"""Workspace discovery: decides which project/workspace an execution
actually runs against, safely and honestly.

This is the fix for a real gap: before Phase 2.2, a `project_name` hint
with no explicit `project_id`/`workspace_path` always fell straight to
`provision_default_workspace` — creating a brand-new directory even when
the caller meant "the project already called that". A task like "Check
config.py in Document Saathi" must never silently create a new
"Document Saathi" directory; it should honestly report that the requested
project was not found, and only genuinely-creation-flavored tasks ("Create
a C++ calculator", with no existing match) provision a new one.

Every path here still goes through `Workspace.at`/`Workspace.resolve` (via
`provision_default_workspace`, which itself only ever writes under
`Settings.workspace_root`) — this module never touches the filesystem
directly and never lets a name/path supplied by a caller escape the
configured LocoPilot Storage root.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.config import get_settings
from backend.app.core.logging import get_logger
from backend.app.db.repositories.projects import create_project, find_project_by_name, get_project
from backend.app.services.workspace_provisioning import provision_default_workspace, slugify
from tools.workspace import Workspace, WorkspaceError

logger = get_logger(component="workspace_discovery")

DiscoveryOutcome = Literal["existing", "created", "not_found", "invalid"]

# Deliberately narrow and explicit rather than an NLP model: a task is
# treated as requesting a brand-new project only when it names one of
# these creation verbs. Anything else (read/fix/check/inspect/refactor/...)
# must find an existing project or fail honestly, never guess.
_CREATION_VERBS = (
    "create", "build", "start", "make", "scaffold", "initialize", "init",
    "set up", "setup", "generate", "bootstrap", "new project",
)

# A light heuristic for "Fix the bug in DeepLens" / "...for Document Saathi"
# style tasks: a capitalized word (or short run of them) following "in"/
# "for"/"inside". This is intentionally simple — an explicit `project_name`
# from the caller always takes precedence over anything extracted here.
_NAME_HINT_PATTERN = re.compile(
    r"\b(?:in|for|inside|within)\s+((?:[A-Z][A-Za-z0-9_-]*)(?:\s+[A-Z][A-Za-z0-9_-]*){0,2})\b"
)


def extract_project_name_hint(task: str) -> str | None:
    match = _NAME_HINT_PATTERN.search(task)
    return match.group(1).strip() if match else None


def task_indicates_creation(task: str) -> bool:
    lowered = task.lower()
    return any(verb in lowered for verb in _CREATION_VERBS)


@dataclass
class WorkspaceDiscoveryResult:
    outcome: DiscoveryOutcome
    project_id: uuid.UUID | None
    project_name: str | None
    workspace_path: str | None
    reason: str


async def _find_directory_on_disk(name: str) -> str | None:
    """Existing projects don't only live in the DB — a directory can exist
    on disk under `<workspace_root>/projects/` without a registered
    `Project` row yet (e.g. uploaded out-of-band). Matched by the same
    slugification `provision_default_workspace` uses to name new
    directories, so a name round-trips correctly either way."""
    projects_root = get_settings().workspace_root / "projects"
    if not projects_root.is_dir():
        return None

    target_slug = slugify(name)
    normalized = name.strip().lower()
    for entry in sorted(projects_root.iterdir()):
        if not entry.is_dir():
            continue
        entry_name = entry.name.lower()
        if entry_name == normalized or entry_name.startswith(f"{target_slug}-") or entry_name == target_slug:
            return str(entry)
    return None


async def discover_or_provision_workspace(
    db: AsyncSession,
    *,
    task: str,
    project_id: uuid.UUID | None,
    workspace_path: str | None,
    project_name: str | None,
) -> WorkspaceDiscoveryResult:
    logger.info("workspace_discovery_started", project_id=str(project_id) if project_id else None, has_workspace_path=bool(workspace_path), has_project_name=bool(project_name))

    # A. Existing project explicitly selected.
    if project_id is not None:
        project = await get_project(db, project_id)
        if project is None:
            logger.warning("workspace_discovery_failed", reason="project_id_not_found")
            return WorkspaceDiscoveryResult(
                outcome="not_found", project_id=None, project_name=None, workspace_path=None,
                reason=f"Project {project_id} was not found.",
            )
        logger.info("workspace_discovery_completed", outcome="existing", project_id=str(project.id))
        return WorkspaceDiscoveryResult(
            outcome="existing", project_id=project.id, project_name=project.name,
            workspace_path=project.workspace_path, reason="Project selected explicitly by id.",
        )

    # An explicit workspace_path is trusted as-is (still validated through
    # the Workspace sandbox boundary) — this is how an existing, non-Git or
    # Git project already on disk is selected without a project_name hint.
    if workspace_path:
        try:
            Workspace.at(workspace_path)
        except WorkspaceError as exc:
            logger.warning("workspace_discovery_failed", reason="invalid_workspace_path", error=str(exc))
            return WorkspaceDiscoveryResult(
                outcome="invalid", project_id=None, project_name=None, workspace_path=None,
                reason=f"Invalid workspace_path: {exc}",
            )
        logger.info("workspace_discovery_completed", outcome="existing", workspace_path=workspace_path)
        return WorkspaceDiscoveryResult(
            outcome="existing", project_id=None, project_name=project_name, workspace_path=workspace_path,
            reason="Workspace path selected explicitly.",
        )

    # B. Existing project by name/path hint — explicit project_name first,
    # then a light heuristic extracted from the task text.
    name_hint = project_name or extract_project_name_hint(task)
    if name_hint:
        existing = await find_project_by_name(db, name_hint)
        if existing is not None:
            logger.info("workspace_discovery_completed", outcome="existing", project_id=str(existing.id), name_hint=name_hint)
            return WorkspaceDiscoveryResult(
                outcome="existing", project_id=existing.id, project_name=existing.name,
                workspace_path=existing.workspace_path, reason=f"Matched existing project by name: {name_hint!r}.",
            )

        disk_path = await _find_directory_on_disk(name_hint)
        if disk_path is not None:
            project = await create_project(db, name=name_hint, workspace_path=disk_path)
            logger.info("workspace_discovery_completed", outcome="existing", project_id=str(project.id), name_hint=name_hint, source="disk")
            return WorkspaceDiscoveryResult(
                outcome="existing", project_id=project.id, project_name=project.name,
                workspace_path=project.workspace_path,
                reason=f"Found an existing workspace directory matching {name_hint!r} on disk.",
            )

        # C/S. Not found anywhere: only provision a new one if the task
        # itself clearly asks for creation — never guess.
        if task_indicates_creation(task):
            new_name, new_path = provision_default_workspace(seed_text=task, project_name=name_hint)
            logger.info("workspace_discovery_completed", outcome="created", name_hint=name_hint)
            return WorkspaceDiscoveryResult(
                outcome="created", project_id=None, project_name=new_name, workspace_path=new_path,
                reason=f"No existing project named {name_hint!r} found; task requested creating a new one.",
            )

        # T. A read/check/fix task naming a project that doesn't exist:
        # an honest failure, never a silently-created empty directory.
        logger.warning("workspace_discovery_failed", reason="project_not_found", name_hint=name_hint)
        return WorkspaceDiscoveryResult(
            outcome="not_found", project_id=None, project_name=None, workspace_path=None,
            reason=f"Requested project/workspace {name_hint!r} was not found.",
        )

    # No id, no path, no name hint at all: preserve the existing "no
    # attachment" default — provision a fresh default workspace, same as
    # before Phase 2.2.
    new_name, new_path = provision_default_workspace(seed_text=task, project_name=None)
    logger.info("workspace_discovery_completed", outcome="created", name_hint=None)
    return WorkspaceDiscoveryResult(
        outcome="created", project_id=None, project_name=new_name, workspace_path=new_path,
        reason="No project reference given; provisioned a new default workspace.",
    )
