"""Phase 2.10 — execution isolation: a traceable per-execution workspace
directory, cross-execution contamination prevention, project-boundary
security, lifecycle transitions, and per-project concurrency safety.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest

from backend.app.services.execution_locks import get_project_execution_lock
from backend.app.services.execution_workspace import (
    ExecutionWorkspaceError,
    cleanup_stale_execution_workspaces,
    create_execution_workspace,
    execution_workspace_root,
    get_execution_workspace_status,
    mark_execution_workspace_status,
)


@pytest.fixture(autouse=True)
def _isolated_workspace_root(tmp_path, monkeypatch):
    from backend.app.core import config as config_module

    monkeypatch.setenv("LOCOPILOT_WORKSPACE_ROOT", str(tmp_path))
    config_module.get_settings.cache_clear()
    yield
    config_module.get_settings.cache_clear()


def test_creates_a_traceable_per_execution_directory() -> None:
    execution_id = str(uuid.uuid4())
    root = create_execution_workspace(execution_id, project_id="proj-1")
    assert root.is_dir()
    assert root.name == execution_id
    assert (root / "execution.json").exists()
    assert get_execution_workspace_status(execution_id) == "created"


def test_cross_execution_contamination_is_impossible() -> None:
    """Execution A's own file must be invisible to Execution B — they are
    different directories entirely, not a shared mutable temp dir."""
    a_id, b_id = str(uuid.uuid4()), str(uuid.uuid4())
    root_a = create_execution_workspace(a_id, project_id="proj-1")
    root_b = create_execution_workspace(b_id, project_id="proj-1")

    (root_a / "marker_from_a.txt").write_text("a's own file", encoding="utf-8")

    assert (root_a / "marker_from_a.txt").exists()
    assert not (root_b / "marker_from_a.txt").exists()
    assert root_a != root_b


def test_lifecycle_transitions_created_active_completed() -> None:
    execution_id = str(uuid.uuid4())
    create_execution_workspace(execution_id, project_id="proj-1")
    assert get_execution_workspace_status(execution_id) == "created"

    mark_execution_workspace_status(execution_id, "active")
    assert get_execution_workspace_status(execution_id) == "active"

    mark_execution_workspace_status(execution_id, "completed")
    assert get_execution_workspace_status(execution_id) == "completed"


def test_failure_leaves_an_accurate_terminal_status_and_does_not_corrupt_others() -> None:
    ok_id, crashed_id = str(uuid.uuid4()), str(uuid.uuid4())
    create_execution_workspace(ok_id, project_id="proj-1")
    create_execution_workspace(crashed_id, project_id="proj-1")

    mark_execution_workspace_status(crashed_id, "active")
    mark_execution_workspace_status(crashed_id, "failed")

    mark_execution_workspace_status(ok_id, "active")
    mark_execution_workspace_status(ok_id, "completed")

    assert get_execution_workspace_status(crashed_id) == "failed"
    assert get_execution_workspace_status(ok_id) == "completed"  # unaffected by the other's crash


def test_invalid_status_is_rejected() -> None:
    execution_id = str(uuid.uuid4())
    create_execution_workspace(execution_id, project_id="proj-1")
    with pytest.raises(ExecutionWorkspaceError):
        mark_execution_workspace_status(execution_id, "not_a_real_status")


@pytest.mark.parametrize(
    "malicious_id",
    ["../../etc", "..\\..\\windows", "a/../../b", "/etc/passwd", "a\\..\\..\\b"],
)
def test_execution_id_path_traversal_is_rejected(malicious_id: str) -> None:
    with pytest.raises(ExecutionWorkspaceError):
        execution_workspace_root(malicious_id)


def test_cleanup_only_removes_terminal_and_expired_workspaces() -> None:
    stale_id, fresh_id, active_id = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
    stale_root = create_execution_workspace(stale_id, project_id="proj-1")
    mark_execution_workspace_status(stale_id, "completed")
    marker = stale_root / "execution.json"
    import json

    data = json.loads(marker.read_text(encoding="utf-8"))
    data["updated_at"] -= 10_000  # simulate an old, already-finished execution
    marker.write_text(json.dumps(data), encoding="utf-8")

    fresh_root = create_execution_workspace(fresh_id, project_id="proj-1")
    mark_execution_workspace_status(fresh_id, "completed")  # terminal but recent

    active_root = create_execution_workspace(active_id, project_id="proj-1")
    mark_execution_workspace_status(active_id, "active")  # never removed regardless of age

    removed = cleanup_stale_execution_workspaces(retention_seconds=60)

    assert stale_id in removed
    assert fresh_id not in removed
    assert active_id not in removed
    # Checked directly, without going back through execution_workspace_root
    # (which would itself recreate the directory it's meant to verify was removed).
    assert not stale_root.exists()
    assert fresh_root.exists()
    assert active_root.exists()


async def test_concurrent_executions_of_the_same_project_are_serialized() -> None:
    project_id = uuid.uuid4()
    order: list[str] = []

    async def run(name: str) -> None:
        async with get_project_execution_lock(project_id):
            order.append(f"{name}-start")
            await asyncio.sleep(0.05)
            order.append(f"{name}-end")

    await asyncio.gather(run("A"), run("B"))

    # One execution's start/end must never interleave with the other's —
    # they share the same real workspace on disk.
    assert order in (["A-start", "A-end", "B-start", "B-end"], ["B-start", "B-end", "A-start", "A-end"])


async def test_different_projects_run_fully_concurrently() -> None:
    project_a, project_b = uuid.uuid4(), uuid.uuid4()
    started = []

    async def run(project_id: uuid.UUID, name: str) -> None:
        async with get_project_execution_lock(project_id):
            started.append(name)
            await asyncio.sleep(0.05)

    await asyncio.wait_for(asyncio.gather(run(project_a, "A"), run(project_b, "B")), timeout=0.2)
    assert set(started) == {"A", "B"}
