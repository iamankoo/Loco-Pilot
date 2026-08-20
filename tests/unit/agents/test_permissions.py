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
    assert "write_file" not in names
    assert "git_create_branch" not in names


def test_developer_has_read_and_write_but_not_git_write() -> None:
    assert DEVELOPER_PERMISSIONS == {Permission.READ, Permission.WRITE}
    names = _names_for(DEVELOPER_PERMISSIONS)
    assert {"read_file", "write_file", "edit_file", "git_status", "git_diff"} <= names
    assert "git_create_branch" not in names


def test_tester_has_read_and_execute() -> None:
    """As of Phase 1.4, Tester is granted EXECUTE now that a real
    execute-capable tool (Docker-backed) exists."""
    assert TESTER_PERMISSIONS == {Permission.READ, Permission.EXECUTE}
    names = _names_for(TESTER_PERMISSIONS)
    assert "execute_terminal_command" in names
    assert "write_file" not in names


def test_debugger_has_read_and_write() -> None:
    assert DEBUGGER_PERMISSIONS == {Permission.READ, Permission.WRITE}


def test_reviewer_is_read_only() -> None:
    assert REVIEWER_PERMISSIONS == {Permission.READ}
    names = _names_for(REVIEWER_PERMISSIONS)
    assert "git_diff" in names and "git_status" in names
    assert "write_file" not in names


async def test_planner_permission_set_cannot_call_execute_tool(tmp_workspace: Workspace) -> None:
    """A Planner-permissioned caller attempting to invoke the execute tool
    is rejected structurally, independent of whether Docker is even
    installed — the permission check happens before the tool ever runs."""
    context = ToolContext(workspace=tmp_workspace)
    runner = BoundToolRunner(registry=build_default_registry(), context=context, permissions=PLANNER_PERMISSIONS)

    with pytest.raises(ToolPermissionError):
        await runner.call("execute_terminal_command", {"command": [sys.executable, "-c", "print(1)"]})
