"""The Docker sandbox: one ephemeral, isolated container bound to one host
workspace directory.

Uses the `docker` CLI via `asyncio.create_subprocess_exec` (never a
shell, never `docker` Python SDK) — the same pattern already used for Git
in `tools/git/tools.py`. Every command this module runs is a fixed argv
list this code constructs; no caller-supplied string ever reaches a
shell.

Lifecycle: `create()` -> `start()` -> `execute()` (repeatable) ->
`destroy()`. Callers MUST call `destroy()` even on failure — see
`tools.terminal.docker_executor.DockerTerminalExecutor` for the
try/finally pattern every caller follows.

Isolation applied to every container, unconditionally: non-root user,
read-only root filesystem (only `/tmp` and the workspace bind mount are
writable), all Linux capabilities dropped, `no-new-privileges`, memory/
CPU/pids limits, and network disabled by default. Verified manually
against this host's Docker Desktop before this file was written: non-root
UID confirmed, writes outside `/workspace`/`/tmp` confirmed rejected,
writes inside `/workspace` confirmed to appear on the host live, and
outbound network confirmed blocked.
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from pathlib import Path

from execution.docker.errors import (
    ArtifactTransferError,
    ContainerCreationError,
    ContainerStartError,
    DockerUnavailableError,
    ImageUnavailableError,
    WorkspaceTransferError,
)
from execution.docker.policy import NetworkPolicy, ResourceLimits
from tools.terminal.contract import TerminalCommandResult
from tools.workspace import Workspace, WorkspaceError

DEFAULT_IMAGE = "locopilot-sandbox-python:1.0"
CONTAINER_NAME_PREFIX = "locopilot-sbx-"
_CONTROL_COMMAND_TIMEOUT = 30


async def _run_docker(*args: str, timeout: float | None = None) -> tuple[int, bytes, bytes]:
    try:
        process = await asyncio.create_subprocess_exec(
            "docker", *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
    except FileNotFoundError as exc:
        raise DockerUnavailableError("docker executable not found on PATH.") from exc

    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
    except asyncio.TimeoutError as exc:
        process.kill()
        await process.communicate()
        raise DockerUnavailableError(f"docker {' '.join(args)} did not respond within {timeout}s.") from exc

    return process.returncode or 0, stdout, stderr


class Sandbox:
    def __init__(
        self,
        workspace: Workspace,
        *,
        image: str = DEFAULT_IMAGE,
        resource_limits: ResourceLimits | None = None,
        network_policy: NetworkPolicy = NetworkPolicy.DISABLED,
    ) -> None:
        self.workspace = workspace
        self.image = image
        self.resource_limits = resource_limits or ResourceLimits()
        self.network_policy = network_policy
        self.name = f"{CONTAINER_NAME_PREFIX}{uuid.uuid4().hex[:12]}"
        self._created = False

    async def create(self) -> None:
        if self.network_policy is NetworkPolicy.RESTRICTED:
            raise NotImplementedError(
                "NetworkPolicy.RESTRICTED is reserved for a later milestone; use DISABLED or ALLOWED."
            )
        network_args = ["--network", "none"] if self.network_policy is NetworkPolicy.DISABLED else []

        args = [
            "create",
            "--name", self.name,
            *network_args,
            "--memory", self.resource_limits.memory,
            "--cpus", self.resource_limits.cpus,
            "--pids-limit", str(self.resource_limits.pids_limit),
            "--security-opt", "no-new-privileges",
            "--cap-drop", "ALL",
            "--read-only",
            "--tmpfs", "/tmp:rw,size=64m",
            "-v", f"{self.workspace.root}:/workspace:rw",
            "--workdir", "/workspace",
            "--user", "1000:1000",
            self.image,
            "sleep", "infinity",
        ]

        code, _, stderr = await _run_docker(*args, timeout=_CONTROL_COMMAND_TIMEOUT)
        if code != 0:
            message = stderr.decode("utf-8", errors="replace").strip()
            if "no such image" in message.lower() or "not found" in message.lower():
                raise ImageUnavailableError(f"Sandbox image not available: {self.image}. {message}")
            raise ContainerCreationError(message)
        self._created = True

    async def start(self) -> None:
        if not self._created:
            raise ContainerStartError("Cannot start a sandbox that has not been created.")
        code, _, stderr = await _run_docker("start", self.name, timeout=_CONTROL_COMMAND_TIMEOUT)
        if code != 0:
            raise ContainerStartError(stderr.decode("utf-8", errors="replace").strip())

    async def execute(
        self,
        command: list[str],
        *,
        cwd: str = ".",
        env: dict[str, str] | None = None,
        timeout_seconds: int | None = None,
        max_output_bytes: int | None = None,
    ) -> TerminalCommandResult:
        """Runs `command` (argv, never a shell string) inside the running
        container. `cwd` is resolved through the same `Workspace` boundary
        checks host-side tools use — a `cwd` containing `..`/an absolute
        path is rejected before it ever reaches `docker exec`, closing the
        same escape class `-w` would otherwise permit (the kernel resolves
        `..` in a working-directory argument regardless of no shell being
        involved).
        """
        try:
            resolved_cwd = self.workspace.resolve(cwd)
        except WorkspaceError as exc:
            raise WorkspaceTransferError(f"Invalid working directory: {exc}") from exc
        relative = self.workspace.relative(resolved_cwd)
        container_cwd = "/workspace" if relative == "." else f"/workspace/{relative}"

        timeout = timeout_seconds or self.resource_limits.timeout_seconds
        output_cap = max_output_bytes or self.resource_limits.max_output_bytes

        # No host environment variable ever reaches the container implicitly
        # — only what the caller explicitly passes via `env` becomes a `-e`
        # flag. The docker CLI subprocess itself inherits the host process's
        # env (to find `docker` on PATH etc), but that is never forwarded
        # into the container.
        exec_args = ["exec", "-w", container_cwd]
        for key, value in (env or {}).items():
            exec_args += ["-e", f"{key}={value}"]
        exec_args += [self.name, *command]

        start = time.monotonic()
        timed_out = False
        try:
            process = await asyncio.create_subprocess_exec(
                "docker", *exec_args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
        except FileNotFoundError as exc:
            raise DockerUnavailableError("docker executable not found on PATH.") from exc

        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(process.communicate(), timeout=timeout)
            exit_code = process.returncode
        except asyncio.TimeoutError:
            timed_out = True
            # A `docker exec` client timing out does not stop the process
            # running inside the container's own namespace — only killing
            # the container itself actually stops a hung command.
            await _run_docker("kill", self.name, timeout=10)
            stdout_bytes, stderr_bytes = await process.communicate()
            exit_code = None

        duration_ms = int((time.monotonic() - start) * 1000)

        return TerminalCommandResult(
            command=command,
            exit_code=exit_code,
            stdout=stdout_bytes[:output_cap].decode("utf-8", errors="replace"),
            stderr=stderr_bytes[:output_cap].decode("utf-8", errors="replace"),
            stdout_truncated=len(stdout_bytes) > output_cap,
            stderr_truncated=len(stderr_bytes) > output_cap,
            duration_ms=duration_ms,
            timed_out=timed_out,
        )

    async def copy_in(self, host_path: Path, container_path: str) -> None:
        """Copies an additional host file/dir into the container, beyond the
        live workspace bind mount. Source must be inside the sandbox's own
        workspace; destination must be under `/workspace`."""
        resolved = host_path.resolve()
        try:
            resolved.relative_to(self.workspace.root)
        except ValueError as exc:
            raise WorkspaceTransferError(f"copy_in source must be inside the sandbox workspace: {host_path}") from exc
        if container_path != "/workspace" and not container_path.startswith("/workspace/"):
            raise WorkspaceTransferError(f"copy_in destination must be under /workspace: {container_path}")

        code, _, stderr = await _run_docker(
            "cp", str(resolved), f"{self.name}:{container_path}", timeout=_CONTROL_COMMAND_TIMEOUT
        )
        if code != 0:
            raise WorkspaceTransferError(stderr.decode("utf-8", errors="replace").strip())

    async def copy_out(self, container_path: str, host_path: Path, *, artifacts_root: Path) -> None:
        """Copies a specific file/dir out of the container to a host
        destination that MUST be inside `artifacts_root` — never an
        arbitrary host path. Source must be under `/workspace`."""
        artifacts_root = artifacts_root.resolve()
        resolved_dest = host_path.resolve()
        try:
            resolved_dest.relative_to(artifacts_root)
        except ValueError as exc:
            raise ArtifactTransferError(
                f"copy_out destination must be inside the artifacts directory {artifacts_root}: {host_path}"
            ) from exc
        if container_path != "/workspace" and not container_path.startswith("/workspace/"):
            raise ArtifactTransferError(f"copy_out source must be under /workspace: {container_path}")

        resolved_dest.parent.mkdir(parents=True, exist_ok=True)
        code, _, stderr = await _run_docker(
            "cp", f"{self.name}:{container_path}", str(resolved_dest), timeout=_CONTROL_COMMAND_TIMEOUT
        )
        if code != 0:
            raise ArtifactTransferError(stderr.decode("utf-8", errors="replace").strip())

    async def inspect(self) -> dict:
        code, stdout, _stderr = await _run_docker("inspect", self.name, timeout=10)
        if code != 0:
            return {"exists": False}
        data = json.loads(stdout.decode("utf-8", errors="replace"))[0]
        state = data.get("State", {})
        return {
            "exists": True,
            "running": state.get("Running", False),
            "status": state.get("Status"),
            "started_at": state.get("StartedAt"),
        }

    async def destroy(self) -> None:
        if not self._created:
            return
        await _run_docker("rm", "-f", self.name, timeout=_CONTROL_COMMAND_TIMEOUT)
        self._created = False
