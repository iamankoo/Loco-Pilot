"""INTERNAL ONLY: a restricted local executor implementing the terminal contract.

Used by tests and future internal tooling to prove the contract works.
Never register this (or wrap it in a `Tool`) for agent/LLM use — it runs
directly on the host process. Phase 1.3 replaces it with a Docker sandbox
that implements the same `TerminalCommandRequest -> TerminalCommandResult`
contract behind a real isolation boundary.
"""

from __future__ import annotations

import asyncio
import time

from tools.terminal.contract import ExecutionPolicy, TerminalCommandRequest, TerminalCommandResult
from tools.workspace import Workspace, WorkspaceError


class TerminalPolicyError(Exception):
    """Raised when a request violates the execution policy, before anything runs."""


class LocalDevTerminalExecutor:
    def __init__(self, workspace: Workspace, policy: ExecutionPolicy | None = None) -> None:
        self._workspace = workspace
        self._policy = policy or ExecutionPolicy()

    async def run(self, request: TerminalCommandRequest) -> TerminalCommandResult:
        if request.timeout_seconds > self._policy.max_timeout_seconds:
            raise TerminalPolicyError(
                f"Requested timeout {request.timeout_seconds}s exceeds policy max "
                f"{self._policy.max_timeout_seconds}s."
            )
        max_output_bytes = min(request.max_output_bytes, self._policy.max_output_bytes)

        try:
            cwd = self._workspace.resolve(request.working_directory)
        except WorkspaceError as exc:
            raise TerminalPolicyError(str(exc)) from exc
        if not cwd.is_dir():
            raise TerminalPolicyError(f"working_directory is not a directory: {request.working_directory}")

        start = time.monotonic()
        process = await asyncio.create_subprocess_exec(
            *request.command,
            cwd=str(cwd),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        timed_out = False
        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                process.communicate(), timeout=request.timeout_seconds
            )
        except asyncio.TimeoutError:
            timed_out = True
            process.kill()
            stdout_bytes, stderr_bytes = await process.communicate()

        duration_ms = int((time.monotonic() - start) * 1000)

        stdout_truncated = len(stdout_bytes) > max_output_bytes
        stderr_truncated = len(stderr_bytes) > max_output_bytes

        return TerminalCommandResult(
            command=request.command,
            exit_code=process.returncode,
            stdout=stdout_bytes[:max_output_bytes].decode("utf-8", errors="replace"),
            stderr=stderr_bytes[:max_output_bytes].decode("utf-8", errors="replace"),
            stdout_truncated=stdout_truncated,
            stderr_truncated=stderr_truncated,
            duration_ms=duration_ms,
            timed_out=timed_out,
        )
