from __future__ import annotations

from execution.docker.policy import ResourceLimits
from execution.docker.sandbox import Sandbox
from tools.workspace import Workspace


async def test_create_start_inspect_destroy_cycle(tmp_workspace: Workspace) -> None:
    sandbox = Sandbox(tmp_workspace, resource_limits=ResourceLimits(timeout_seconds=10))
    try:
        await sandbox.create()
        await sandbox.start()
        info = await sandbox.inspect()
        assert info["exists"] is True
        assert info["running"] is True
    finally:
        await sandbox.destroy()

    assert (await sandbox.inspect())["exists"] is False


async def test_execute_returns_real_exit_code_and_stdout(tmp_workspace: Workspace) -> None:
    sandbox = Sandbox(tmp_workspace, resource_limits=ResourceLimits(timeout_seconds=10))
    try:
        await sandbox.create()
        await sandbox.start()
        result = await sandbox.execute(["python", "-c", "print('hi')"])
        assert result.exit_code == 0
        assert "hi" in result.stdout
    finally:
        await sandbox.destroy()


async def test_execute_captures_nonzero_exit_code_and_stderr(tmp_workspace: Workspace) -> None:
    sandbox = Sandbox(tmp_workspace, resource_limits=ResourceLimits(timeout_seconds=10))
    try:
        await sandbox.create()
        await sandbox.start()
        result = await sandbox.execute(
            ["python", "-c", "import sys; sys.stderr.write('boom'); sys.exit(2)"]
        )
        assert result.exit_code == 2
        assert "boom" in result.stderr
    finally:
        await sandbox.destroy()


async def test_execute_can_read_workspace_file(tmp_workspace: Workspace) -> None:
    (tmp_workspace.root / "hello.py").write_text("print('from workspace')\n", encoding="utf-8")
    sandbox = Sandbox(tmp_workspace, resource_limits=ResourceLimits(timeout_seconds=10))
    try:
        await sandbox.create()
        await sandbox.start()
        result = await sandbox.execute(["python", "hello.py"])
        assert result.exit_code == 0
        assert "from workspace" in result.stdout
    finally:
        await sandbox.destroy()


async def test_timeout_is_enforced_and_container_is_killed(tmp_workspace: Workspace) -> None:
    sandbox = Sandbox(tmp_workspace, resource_limits=ResourceLimits(timeout_seconds=1))
    try:
        await sandbox.create()
        await sandbox.start()
        result = await sandbox.execute(["python", "-c", "import time; time.sleep(10)"])
        assert result.timed_out is True
        assert result.duration_ms < 5000
    finally:
        await sandbox.destroy()


async def test_output_is_truncated_at_configured_limit(tmp_workspace: Workspace) -> None:
    sandbox = Sandbox(tmp_workspace, resource_limits=ResourceLimits(timeout_seconds=10, max_output_bytes=100))
    try:
        await sandbox.create()
        await sandbox.start()
        result = await sandbox.execute(["python", "-c", "print('x' * 10000)"])
        assert result.stdout_truncated is True
        assert len(result.stdout) <= 100
    finally:
        await sandbox.destroy()


async def test_destroy_is_idempotent(tmp_workspace: Workspace) -> None:
    sandbox = Sandbox(tmp_workspace)
    await sandbox.create()
    await sandbox.start()
    await sandbox.destroy()
    await sandbox.destroy()  # must not raise


async def test_cleanup_after_exception_leaves_no_container(tmp_workspace: Workspace) -> None:
    sandbox = Sandbox(tmp_workspace, resource_limits=ResourceLimits(timeout_seconds=10))
    await sandbox.create()
    await sandbox.start()
    try:
        try:
            raise RuntimeError("simulated failure mid-execution")
        finally:
            await sandbox.destroy()
    except RuntimeError:
        pass

    assert (await sandbox.inspect())["exists"] is False
