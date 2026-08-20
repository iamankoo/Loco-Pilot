from __future__ import annotations

import subprocess

from execution.docker.sandbox import CONTAINER_NAME_PREFIX
from tools.terminal.contract import TerminalCommandRequest
from tools.terminal.docker_executor import DockerTerminalExecutor
from tools.workspace import Workspace


def _sandbox_container_names() -> str:
    return subprocess.run(
        ["docker", "ps", "-a", "--filter", f"name={CONTAINER_NAME_PREFIX}", "--format", "{{.Names}}"],
        capture_output=True,
        text=True,
    ).stdout


async def test_executor_returns_real_result(tmp_workspace: Workspace) -> None:
    executor = DockerTerminalExecutor(tmp_workspace)
    result = await executor.run(TerminalCommandRequest(command=["python", "-c", "print('hi')"]))
    assert result.exit_code == 0
    assert "hi" in result.stdout


async def test_executor_cleans_up_container_after_successful_run(tmp_workspace: Workspace) -> None:
    before = _sandbox_container_names()
    executor = DockerTerminalExecutor(tmp_workspace)
    await executor.run(TerminalCommandRequest(command=["python", "-c", "print(1)"]))
    after = _sandbox_container_names()
    assert after == before


async def test_executor_cleans_up_container_after_command_failure(tmp_workspace: Workspace) -> None:
    before = _sandbox_container_names()
    executor = DockerTerminalExecutor(tmp_workspace)
    await executor.run(TerminalCommandRequest(command=["python", "-c", "import sys; sys.exit(1)"]))
    after = _sandbox_container_names()
    assert after == before


async def test_executor_cleans_up_container_after_timeout(tmp_workspace: Workspace) -> None:
    before = _sandbox_container_names()
    executor = DockerTerminalExecutor(tmp_workspace)
    result = await executor.run(
        TerminalCommandRequest(command=["python", "-c", "import time; time.sleep(10)"], timeout_seconds=1)
    )
    assert result.timed_out is True
    after = _sandbox_container_names()
    assert after == before
