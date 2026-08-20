"""The real, production terminal executor — backed by the Docker sandbox.

Implements the exact same `TerminalCommandRequest -> TerminalCommandResult`
contract as `LocalDevTerminalExecutor` (Phase 1.2's internal-only dev/test
executor), so `ExecuteTerminalCommandTool` doesn't need to know which
backend it's using. One sandbox container is created per call and always
destroyed in a `finally` block, regardless of success, failure, or
timeout — no abandoned containers.
"""

from __future__ import annotations

from execution.docker.policy import NetworkPolicy, ResourceLimits
from execution.docker.sandbox import DEFAULT_IMAGE, Sandbox
from tools.terminal.contract import ExecutionPolicy, TerminalCommandRequest, TerminalCommandResult
from tools.workspace import Workspace


class DockerTerminalExecutor:
    def __init__(
        self,
        workspace: Workspace,
        policy: ExecutionPolicy | None = None,
        *,
        image: str = DEFAULT_IMAGE,
    ) -> None:
        self._workspace = workspace
        self._policy = policy or ExecutionPolicy()
        self._image = image

    async def run(self, request: TerminalCommandRequest) -> TerminalCommandResult:
        resource_limits = ResourceLimits(
            timeout_seconds=min(request.timeout_seconds, self._policy.max_timeout_seconds),
            max_output_bytes=min(request.max_output_bytes, self._policy.max_output_bytes),
        )
        network_policy = NetworkPolicy.ALLOWED if self._policy.allow_network else NetworkPolicy.DISABLED

        sandbox = Sandbox(
            self._workspace,
            image=self._image,
            resource_limits=resource_limits,
            network_policy=network_policy,
        )
        try:
            await sandbox.create()
            await sandbox.start()
            return await sandbox.execute(
                request.command,
                cwd=request.working_directory,
                timeout_seconds=resource_limits.timeout_seconds,
                max_output_bytes=resource_limits.max_output_bytes,
            )
        finally:
            await sandbox.destroy()
