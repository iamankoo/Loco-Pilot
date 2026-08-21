"""Phase 2.10: a per-execution, traceable workspace directory.

LocoPilot's core value is editing a project's *real* files — Developer's
tools operate directly on `project.workspace_path`, not a throwaway copy,
and that is intentional (see README "Workspace storage"). Full per-execution
duplication of the entire project would silently change that guarantee and
was deliberately not done here.

What Phase 2.10 actually isolates is everything *execution-scoped* that
previously had nowhere dedicated to live: a traceable directory per
execution (`<workspace_root>/executions/<execution_id>/`) for this
execution's own lifecycle marker and any scratch/artifact files a future
phase (e.g. Phase 2.11 reports) writes — so Execution A's own files are
never visible to, or writable by, Execution B, even though both may act on
the same project's shared source tree. Concurrency safety for that shared
source tree is handled separately by `execution_locks.py`.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

from backend.app.core.config import get_settings

_VALID_EXECUTION_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_\-]*$")

_LIFECYCLE_STATUSES = {"created", "active", "completed", "failed", "cancelled"}


class ExecutionWorkspaceError(Exception):
    pass


def _validate_execution_id(execution_id: str) -> str:
    # Defense in depth: execution_id is normally a UUID from the DB, but
    # this directory name is derived from it directly, so it must never be
    # allowed to smuggle a path-traversal segment (`..`, `/`, `\`) into the
    # executions root.
    if not _VALID_EXECUTION_ID.match(execution_id) or ".." in execution_id:
        raise ExecutionWorkspaceError(f"Invalid execution_id for workspace isolation: {execution_id!r}")
    return execution_id


def execution_workspace_root(execution_id: str) -> Path:
    """`<workspace_root>/executions/<execution_id>/` — created if absent.
    Never touches `project.workspace_path`; this is purely execution-scoped
    storage, independent of and additional to the project's own files."""
    execution_id = _validate_execution_id(execution_id)
    root = get_settings().workspace_root / "executions" / execution_id
    root.mkdir(parents=True, exist_ok=True)
    return root


def _marker_path(execution_id: str) -> Path:
    return execution_workspace_root(execution_id) / "execution.json"


def create_execution_workspace(execution_id: str, *, project_id: str) -> Path:
    """Idempotent CREATED-state initialization. Safe to call more than
    once for the same execution_id (e.g. on a retried background task)."""
    root = execution_workspace_root(execution_id)
    marker = _marker_path(execution_id)
    if not marker.exists():
        _write_marker(execution_id, project_id=project_id, status="created", created_at=time.time())
    return root


def mark_execution_workspace_status(execution_id: str, status: str) -> None:
    """Advances the lifecycle marker: created -> active ->
    completed|failed|cancelled. Never deletes anything — cleanup is a
    separate, explicit, opt-in action (see `cleanup_execution_workspace`)."""
    if status not in _LIFECYCLE_STATUSES:
        raise ExecutionWorkspaceError(f"Unknown execution workspace status: {status!r}")
    marker = _marker_path(execution_id)
    data = _read_marker(execution_id) if marker.exists() else {
        "execution_id": execution_id,
        "project_id": None,
        "created_at": time.time(),
    }
    data["status"] = status
    data["updated_at"] = time.time()
    marker.write_text(json.dumps(data), encoding="utf-8")


def _write_marker(execution_id: str, *, project_id: str, status: str, created_at: float) -> None:
    marker = _marker_path(execution_id)
    marker.write_text(
        json.dumps(
            {
                "execution_id": execution_id,
                "project_id": project_id,
                "status": status,
                "created_at": created_at,
                "updated_at": created_at,
            }
        ),
        encoding="utf-8",
    )


def _read_marker(execution_id: str) -> dict:
    marker = _marker_path(execution_id)
    if not marker.exists():
        raise ExecutionWorkspaceError(f"No execution workspace exists for {execution_id!r}")
    return json.loads(marker.read_text(encoding="utf-8"))


def get_execution_workspace_status(execution_id: str) -> str:
    return _read_marker(execution_id)["status"]


def cleanup_stale_execution_workspaces(*, retention_seconds: float) -> list[str]:
    """Deletes only execution workspaces whose lifecycle already reached a
    terminal state (completed/failed/cancelled) AND whose last update is
    older than `retention_seconds` — never a running (created/active) one,
    and never the project's own workspace, which this function never even
    looks at. Not called automatically anywhere; a deliberate, explicit
    maintenance action so retention stays safe and predictable rather than
    silently deleting artifacts a report might still need."""
    import shutil

    executions_root = get_settings().workspace_root / "executions"
    removed: list[str] = []
    if not executions_root.exists():
        return removed

    now = time.time()
    for entry in executions_root.iterdir():
        if not entry.is_dir():
            continue
        marker = entry / "execution.json"
        if not marker.exists():
            continue
        try:
            data = json.loads(marker.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if data.get("status") not in ("completed", "failed", "cancelled"):
            continue
        if now - data.get("updated_at", now) < retention_seconds:
            continue
        shutil.rmtree(entry, ignore_errors=True)
        removed.append(entry.name)
    return removed
