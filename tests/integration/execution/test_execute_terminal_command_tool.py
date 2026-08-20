from __future__ import annotations

import pytest
from pydantic import ValidationError

from tools.base import Permission, ToolContext
from tools.terminal.contract import TerminalCommandRequest
from tools.terminal.tools import ExecuteTerminalCommandTool
from tools.workspace import Workspace


async def test_tool_executes_a_real_command(tmp_workspace: Workspace) -> None:
    tool = ExecuteTerminalCommandTool()
    context = ToolContext(workspace=tmp_workspace)
    result = await tool.run(TerminalCommandRequest(command=["python", "-c", "print('ok')"]), context)
    assert result.exit_code == 0
    assert "ok" in result.stdout


def test_tool_input_rejects_empty_argv() -> None:
    with pytest.raises(ValidationError):
        TerminalCommandRequest(command=[])


def test_tool_declares_execute_permission() -> None:
    assert ExecuteTerminalCommandTool.permission == Permission.EXECUTE
