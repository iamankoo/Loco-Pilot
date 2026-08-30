"""A long-lived, localhost-only runtime container for verifying a
generated application actually serves traffic — the "run it on localhost"
half of LocoPilot's execution architecture.

Distinct from the one-shot `tools.terminal.docker_executor` path: a
`Sandbox` here is created once, its serve command is launched via
`Sandbox.execute_detached` (so it outlives the call that started it), and
the container is torn down explicitly via `.stop()` — never left running
indefinitely (see `backend.app.services.runtime_service` for the bounded
lifetime/cleanup policy every runtime is actually subject to).

Never reachable except from this machine: the published port is always
bound to 127.0.0.1 (`execution.docker.policy.PortPublish`), and the
container keeps every OTHER isolation guarantee the one-shot command
sandbox has (non-root, read-only root filesystem, dropped capabilities,
resource-limited). The only differences from a one-shot command sandbox
are NetworkPolicy.ALLOWED (required for the port publish to have a bridge
interface to forward through at all) and a longer effective lifetime.
"""

from __future__ import annotations

import asyncio

import httpx

from execution.docker.policy import NetworkPolicy, PortPublish, ResourceLimits
from execution.docker.sandbox import Sandbox
from tools.workspace import Workspace

RUNTIME_CONTAINER_PREFIX = "locopilot-rt-"
_READY_POLL_INTERVAL_SECONDS = 0.5


class RuntimeStartError(Exception):
    """The runtime container/process could not be started at all — distinct
    from a started-but-never-became-reachable runtime (see `wait_until_ready`)."""


class ManagedRuntime:
    def __init__(
        self,
        workspace: Workspace,
        *,
        command: list[str],
        container_port: int,
        host_port: int,
        image: str,
        resource_limits: ResourceLimits | None = None,
    ) -> None:
        self.command = command
        self.container_port = container_port
        self.host_port = host_port
        self._sandbox = Sandbox(
            workspace,
            image=image,
            resource_limits=resource_limits or ResourceLimits(),
            network_policy=NetworkPolicy.ALLOWED,
            name_prefix=RUNTIME_CONTAINER_PREFIX,
            ports=[PortPublish(container_port=container_port, host_port=host_port)],
        )

    @property
    def container_name(self) -> str:
        return self._sandbox.name

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.host_port}"

    async def start(self) -> None:
        try:
            await self._sandbox.create()
            await self._sandbox.start()
            await self._sandbox.execute_detached(self.command)
        except Exception as exc:  # noqa: BLE001 - always surfaced as RuntimeStartError, container always cleaned up
            await self.stop()
            raise RuntimeStartError(str(exc)) from exc

    async def wait_until_ready(self, *, path: str = "/", timeout_seconds: float = 20.0) -> tuple[bool, str]:
        """Polls `url + path` until it returns any HTTP response (any status
        code counts as "the server is up" — even a 404 proves the process is
        listening; verifying the RIGHT content is a separate, higher-level
        check) or `timeout_seconds` elapses. Never raises — returns
        `(False, reason)` on failure so the caller reports real evidence
        rather than propagating an exception."""
        loop = asyncio.get_event_loop()
        deadline = loop.time() + timeout_seconds
        last_error = "not attempted"
        async with httpx.AsyncClient(timeout=3.0) as client:
            while loop.time() < deadline:
                try:
                    response = await client.get(self.url + path)
                    return True, f"HTTP {response.status_code}"
                except httpx.HTTPError as exc:
                    last_error = str(exc)
                await asyncio.sleep(_READY_POLL_INTERVAL_SECONDS)
        return False, f"Server never became reachable at {self.url}: {last_error}"

    async def stop(self) -> None:
        await self._sandbox.destroy()
