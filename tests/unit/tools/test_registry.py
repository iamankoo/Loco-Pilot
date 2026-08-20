from __future__ import annotations

import pytest
from pydantic import BaseModel

from tools.base import Permission, Tool, ToolContext
from tools.registry import READ_ONLY, ToolNotFoundError, ToolRegistry, build_default_registry


class _DummyInput(BaseModel):
    value: str


class _DummyOutput(BaseModel):
    result: str


class _DummyTool(Tool[_DummyInput, _DummyOutput]):
    name = "dummy_tool"
    description = "A dummy tool for registry tests."
    permission = Permission.READ
    input_model = _DummyInput
    output_model = _DummyOutput

    async def run(self, tool_input: _DummyInput, context: ToolContext) -> _DummyOutput:
        return _DummyOutput(result=tool_input.value.upper())


def test_register_and_get() -> None:
    registry = ToolRegistry()
    registry.register(_DummyTool())
    assert registry.get("dummy_tool").name == "dummy_tool"


def test_register_duplicate_raises() -> None:
    registry = ToolRegistry()
    registry.register(_DummyTool())
    with pytest.raises(ValueError):
        registry.register(_DummyTool())


def test_get_unknown_tool_raises() -> None:
    registry = ToolRegistry()
    with pytest.raises(ToolNotFoundError):
        registry.get("does_not_exist")


def test_has_reports_existence() -> None:
    registry = ToolRegistry()
    assert registry.has("dummy_tool") is False
    registry.register(_DummyTool())
    assert registry.has("dummy_tool") is True


def test_list_tools_filters_by_permission() -> None:
    registry = ToolRegistry()
    registry.register(_DummyTool())
    assert [t.name for t in registry.list_tools(permissions={Permission.READ})] == ["dummy_tool"]
    assert registry.list_tools(permissions={Permission.WRITE}) == []


def test_schemas_exposes_input_and_output_schema() -> None:
    registry = ToolRegistry()
    registry.register(_DummyTool())
    schemas = registry.schemas()
    assert schemas[0]["name"] == "dummy_tool"
    assert "properties" in schemas[0]["input_schema"]
    assert "properties" in schemas[0]["output_schema"]


def test_default_registry_has_expected_tools() -> None:
    expected = {
        "list_directory",
        "read_file",
        "write_file",
        "edit_file",
        "search_files",
        "git_status",
        "git_diff",
        "git_branch",
        "git_create_branch",
    }
    names = {t.name for t in build_default_registry().list_tools()}
    assert expected <= names


def test_default_registry_excludes_git_commit_and_execute_tools() -> None:
    registry = build_default_registry()
    names = {t.name for t in registry.list_tools()}
    assert "git_commit" not in names
    assert not any(t.permission == Permission.EXECUTE for t in registry.list_tools())


def test_read_only_permission_set_excludes_write_tools() -> None:
    names = {t.name for t in build_default_registry().list_tools(permissions=READ_ONLY)}
    assert "write_file" not in names
    assert "read_file" in names
