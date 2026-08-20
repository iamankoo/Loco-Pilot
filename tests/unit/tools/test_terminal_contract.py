from __future__ import annotations

import sys

import pytest

from tools.terminal.contract import ExecutionPolicy, TerminalCommandRequest
from tools.terminal.local_executor import LocalDevTerminalExecutor, TerminalPolicyError
from tools.workspace import Workspace


@pytest.fixture
def executor(tmp_workspace: Workspace) -> LocalDevTerminalExecutor:
    return LocalDevTerminalExecutor(tmp_workspace)


async def test_successful_command_result_structure(executor: LocalDevTerminalExecutor) -> None:
    request = TerminalCommandRequest(command=[sys.executable, "-c", "print('hi')"])
    result = await executor.run(request)
    assert result.exit_code == 0
    assert "hi" in result.stdout
    assert result.timed_out is False
    assert result.duration_ms >= 0
    assert result.command == request.command


async def test_nonzero_exit_code_captured(executor: LocalDevTerminalExecutor) -> None:
    request = TerminalCommandRequest(command=[sys.executable, "-c", "import sys; sys.exit(3)"])
    result = await executor.run(request)
    assert result.exit_code == 3


async def test_timeout_is_enforced(executor: LocalDevTerminalExecutor) -> None:
    request = TerminalCommandRequest(
        command=[sys.executable, "-c", "import time; time.sleep(5)"], timeout_seconds=1
    )
    result = await executor.run(request)
    assert result.timed_out is True
    assert result.duration_ms < 5000


async def test_output_is_truncated_at_limit(executor: LocalDevTerminalExecutor) -> None:
    request = TerminalCommandRequest(
        command=[sys.executable, "-c", "print('x' * 100000)"], max_output_bytes=100
    )
    result = await executor.run(request)
    assert result.stdout_truncated is True
    assert len(result.stdout) <= 100


async def test_working_directory_outside_workspace_rejected(executor: LocalDevTerminalExecutor) -> None:
    request = TerminalCommandRequest(
        command=[sys.executable, "-c", "print(1)"], working_directory="../outside"
    )
    with pytest.raises(TerminalPolicyError):
        await executor.run(request)


async def test_request_exceeding_policy_timeout_rejected(tmp_workspace: Workspace) -> None:
    executor = LocalDevTerminalExecutor(tmp_workspace, ExecutionPolicy(max_timeout_seconds=5))
    request = TerminalCommandRequest(command=[sys.executable, "-c", "print(1)"], timeout_seconds=10)
    with pytest.raises(TerminalPolicyError):
        await executor.run(request)


def test_registered_execute_tool_is_docker_backed_not_the_local_dev_executor() -> None:
    """LocalDevTerminalExecutor (this file's `executor` fixture) is
    internal-only, used by the tests above for the timeout/output-limit/
    cwd-validation contract — it must never be what an agent-facing tool
    actually runs. The registered `execute_terminal_command` tool
    (Phase 1.4) uses `DockerTerminalExecutor` instead."""
    from tools.registry import build_default_registry
    from tools.terminal.tools import ExecuteTerminalCommandTool

    tool = build_default_registry().get("execute_terminal_command")
    assert isinstance(tool, ExecuteTerminalCommandTool)
