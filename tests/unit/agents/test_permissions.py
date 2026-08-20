from __future__ import annotations

from agents.permissions import (
    DEBUGGER_PERMISSIONS,
    DEVELOPER_PERMISSIONS,
    PLANNER_PERMISSIONS,
    REVIEWER_PERMISSIONS,
    TESTER_PERMISSIONS,
)
from tools.base import Permission
from tools.registry import build_default_registry


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


def test_tester_is_read_only_today() -> None:
    assert TESTER_PERMISSIONS == {Permission.READ}
    names = _names_for(TESTER_PERMISSIONS)
    assert "run_tests" not in names
    assert "execute_terminal_command" not in names


def test_debugger_has_read_and_write() -> None:
    assert DEBUGGER_PERMISSIONS == {Permission.READ, Permission.WRITE}


def test_reviewer_is_read_only() -> None:
    assert REVIEWER_PERMISSIONS == {Permission.READ}
    names = _names_for(REVIEWER_PERMISSIONS)
    assert "git_diff" in names and "git_status" in names
    assert "write_file" not in names
