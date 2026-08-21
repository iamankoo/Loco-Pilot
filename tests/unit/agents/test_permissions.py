from __future__ import annotations

import sys

import pytest

from agents.permissions import (
    DEBUGGER_PERMISSIONS,
    DEVELOPER_PERMISSIONS,
    PLANNER_PERMISSIONS,
    REVIEWER_PERMISSIONS,
    TESTER_PERMISSIONS,
)
from backend.app.services.tool_execution import BoundToolRunner
from tools.base import Permission, ToolContext, ToolPermissionError
from tools.registry import build_default_registry
from tools.workspace import Workspace


def _names_for(permissions: set[Permission]) -> set[str]:
    return {t.name for t in build_default_registry().list_tools(permissions=permissions)}


def test_planner_is_read_only() -> None:
    assert PLANNER_PERMISSIONS == {Permission.READ}
    names = _names_for(PLANNER_PERMISSIONS)
    assert "read_file" in names and "search_files" in names and "list_directory" in names
    assert "file_exists" in names
    assert "write_file" not in names
    assert "delete_file" not in names
    assert "move_file" not in names
    assert "git_create_branch" not in names


def test_developer_has_read_and_write_but_not_git_write() -> None:
    assert DEVELOPER_PERMISSIONS == {Permission.READ, Permission.WRITE}
    names = _names_for(DEVELOPER_PERMISSIONS)
    assert {"read_file", "write_file", "edit_file", "delete_file", "move_file", "git_status", "git_diff"} <= names
    assert "git_create_branch" not in names


def test_tester_has_read_and_execute() -> None:
    """As of Phase 1.4, Tester is granted EXECUTE now that a real
    execute-capable tool (Docker-backed) exists."""
    assert TESTER_PERMISSIONS == {Permission.READ, Permission.EXECUTE}
    names = _names_for(TESTER_PERMISSIONS)
    assert "execute_terminal_command" in names
    assert "write_file" not in names
    assert "delete_file" not in names
    assert "move_file" not in names


def test_debugger_has_read_and_write() -> None:
    assert DEBUGGER_PERMISSIONS == {Permission.READ, Permission.WRITE}


def test_debugger_tool_allowlist_stays_read_only_despite_write_permission() -> None:
    """DEBUGGER_PERMISSIONS grants WRITE at the permission-table level (for
    interface completeness), but `agents.graph`'s node wrapper further
    restricts Debugger's actual tool-calling loop to a read-only allowlist
    — Phase 2.3 added file_exists/delete_file/move_file tools, and none of
    the mutating ones may be added to that allowlist without deliberately
    changing this architecture decision."""
    from agents.graph import _DEBUGGER_TOOL_NAMES

    assert "file_exists" in _DEBUGGER_TOOL_NAMES
    assert "write_file" not in _DEBUGGER_TOOL_NAMES
    assert "edit_file" not in _DEBUGGER_TOOL_NAMES
    assert "delete_file" not in _DEBUGGER_TOOL_NAMES
    assert "move_file" not in _DEBUGGER_TOOL_NAMES


def test_reviewer_is_read_only() -> None:
    assert REVIEWER_PERMISSIONS == {Permission.READ}
    names = _names_for(REVIEWER_PERMISSIONS)
    assert "git_diff" in names and "git_status" in names
    assert "write_file" not in names
    assert "delete_file" not in names
    assert "move_file" not in names


async def test_planner_cannot_delete_or_move_files(tmp_workspace: Workspace) -> None:
    context = ToolContext(workspace=tmp_workspace)
    runner = BoundToolRunner(registry=build_default_registry(), context=context, permissions=PLANNER_PERMISSIONS)

    with pytest.raises(ToolPermissionError):
        await runner.call("delete_file", {"path": "a.txt"})
    with pytest.raises(ToolPermissionError):
        await runner.call("move_file", {"source_path": "a.txt", "destination_path": "b.txt"})


async def test_reviewer_cannot_delete_or_write_files(tmp_workspace: Workspace) -> None:
    context = ToolContext(workspace=tmp_workspace)
    runner = BoundToolRunner(registry=build_default_registry(), context=context, permissions=REVIEWER_PERMISSIONS)

    with pytest.raises(ToolPermissionError):
        await runner.call("delete_file", {"path": "a.txt"})
    with pytest.raises(ToolPermissionError):
        await runner.call("write_file", {"path": "a.txt", "content": "x"})


async def test_tester_cannot_mutate_files(tmp_workspace: Workspace) -> None:
    context = ToolContext(workspace=tmp_workspace)
    runner = BoundToolRunner(registry=build_default_registry(), context=context, permissions=TESTER_PERMISSIONS)

    with pytest.raises(ToolPermissionError):
        await runner.call("write_file", {"path": "a.txt", "content": "x"})
    with pytest.raises(ToolPermissionError):
        await runner.call("delete_file", {"path": "a.txt"})
    with pytest.raises(ToolPermissionError):
        await runner.call("move_file", {"source_path": "a.txt", "destination_path": "b.txt"})


async def test_developer_can_delete_and_move_files(tmp_workspace: Workspace) -> None:
    (tmp_workspace.root / "a.txt").write_text("x")
    context = ToolContext(workspace=tmp_workspace)
    runner = BoundToolRunner(registry=build_default_registry(), context=context, permissions=DEVELOPER_PERMISSIONS)

    move_result = await runner.call("move_file", {"source_path": "a.txt", "destination_path": "b.txt"})
    assert move_result.status == "success"
    delete_result = await runner.call("delete_file", {"path": "b.txt"})
    assert delete_result.status == "success"


async def test_planner_permission_set_cannot_call_execute_tool(tmp_workspace: Workspace) -> None:
    """A Planner-permissioned caller attempting to invoke the execute tool
    is rejected structurally, independent of whether Docker is even
    installed — the permission check happens before the tool ever runs."""
    context = ToolContext(workspace=tmp_workspace)
    runner = BoundToolRunner(registry=build_default_registry(), context=context, permissions=PLANNER_PERMISSIONS)

    with pytest.raises(ToolPermissionError):
        await runner.call("execute_terminal_command", {"command": [sys.executable, "-c", "print(1)"]})
