"""In-process registry of live `ManagedRuntime` instances, one per execution.

A runtime is deliberately kept alive past its own execution's graph
completion (Tester starts and verifies it; nothing later in the graph
stops it) so the "Open in Browser" link the frontend shows after the run
finishes is not already dead the moment it appears — see
`backend.app.api.v1.executions`'s `/runtime` read endpoint and
`/runtime/stop` action. Bounded by a per-runtime expiry: `sweep_expired`
(called from a background task started in `backend.app.main`'s lifespan)
stops anything past its recorded expiry, so nothing runs forever merely
because nobody clicked "stop".

This registry is intentionally NOT persisted to the database — if the
backend process restarts, every previously-tracked runtime is already gone
from this process's memory, and `get_status` for an untracked execution
honestly reports "no_runtime" rather than fabricating state. The
underlying Docker containers, however, DO outlive a backend restart, so
`sweep_orphaned_containers` (also called at startup) stops any leftover
`locopilot-rt-*` container from a previous process life.
"""

from __future__ import annotations

import asyncio
import socket
import time
from dataclasses import dataclass
from typing import Literal

from execution.docker.runtime import RUNTIME_CONTAINER_PREFIX, ManagedRuntime, RuntimeStartError
from execution.docker.sandbox import DEFAULT_IMAGE, run_docker
from backend.app.core.logging import get_logger
from tools.workspace import Workspace

logger = get_logger(component="runtime_service")

RuntimeStatus = Literal["starting", "running", "verification_failed", "start_failed", "stopped"]

# A bounded, generous window to open the result after a run finishes — not
# an unattended long-lived service. Callers may pass a shorter value.
DEFAULT_MAX_LIFETIME_SECONDS = 30 * 60


@dataclass
class RuntimeRecord:
    execution_id: str
    runtime: ManagedRuntime
    status: RuntimeStatus
    detail: str
    expires_at: float


_registry: dict[str, RuntimeRecord] = {}
_lock = asyncio.Lock()


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def start_runtime(
    execution_id: str,
    workspace: Workspace,
    *,
    command: list[str],
    container_port: int,
    image: str = DEFAULT_IMAGE,
    max_lifetime_seconds: int = DEFAULT_MAX_LIFETIME_SECONDS,
    ready_path: str = "/",
    ready_timeout_seconds: float = 20.0,
) -> RuntimeRecord:
    """Starts a runtime for `execution_id` (stopping any prior one for the
    same execution first) and blocks until it is either verified reachable
    or has definitively failed to become reachable. Never raises — every
    outcome (start failure, never-became-reachable, success) is reported
    through the returned record's `status`/`detail`, which is real evidence
    a caller (Tester) can put directly into a `TestResult`."""
    if execution_id in _registry:
        await stop_runtime(execution_id)

    host_port = _find_free_port()
    runtime = ManagedRuntime(
        workspace, command=command, container_port=container_port, host_port=host_port, image=image
    )
    record = RuntimeRecord(
        execution_id=execution_id,
        runtime=runtime,
        status="starting",
        detail="Starting runtime container.",
        expires_at=time.monotonic() + max_lifetime_seconds,
    )
    async with _lock:
        _registry[execution_id] = record

    try:
        await runtime.start()
    except RuntimeStartError as exc:
        record.status = "start_failed"
        record.detail = str(exc)
        logger.warning("runtime_start_failed", execution_id=execution_id, error=str(exc))
        async with _lock:
            _registry.pop(execution_id, None)
        return record

    logger.info("runtime_started", execution_id=execution_id, url=runtime.url)
    ready, detail = await runtime.wait_until_ready(path=ready_path, timeout_seconds=ready_timeout_seconds)
    record.detail = detail
    if ready:
        record.status = "running"
        logger.info("runtime_verification_completed", execution_id=execution_id, url=runtime.url, ok=True)
        return record

    record.status = "verification_failed"
    logger.warning("runtime_verification_completed", execution_id=execution_id, url=runtime.url, ok=False, detail=detail)
    # A container that never became reachable is not left running.
    await runtime.stop()
    async with _lock:
        _registry.pop(execution_id, None)
    return record


async def get_status(execution_id: str) -> dict:
    async with _lock:
        record = _registry.get(execution_id)
    if record is None:
        return {"status": "no_runtime", "url": None, "detail": None}
    if time.monotonic() > record.expires_at:
        await stop_runtime(execution_id)
        return {"status": "stopped", "url": record.runtime.url, "detail": "Runtime lifetime expired."}
    return {
        "status": record.status,
        "url": record.runtime.url if record.status in ("starting", "running") else None,
        "detail": record.detail,
    }


async def stop_runtime(execution_id: str) -> bool:
    async with _lock:
        record = _registry.pop(execution_id, None)
    if record is None:
        return False
    await record.runtime.stop()
    logger.info("runtime_stopped", execution_id=execution_id)
    return True


async def sweep_expired() -> None:
    async with _lock:
        expired = [eid for eid, r in _registry.items() if time.monotonic() > r.expires_at]
    for eid in expired:
        await stop_runtime(eid)


async def sweep_orphaned_containers() -> None:
    """Best-effort startup cleanup: stop any `locopilot-rt-*` container left
    running from a previous backend process life — this registry is
    in-memory and does not survive a restart, but the underlying Docker
    containers do."""
    try:
        code, stdout, _stderr = await run_docker(
            "ps", "-q", "--filter", f"name={RUNTIME_CONTAINER_PREFIX}", timeout=10
        )
    except Exception as exc:  # noqa: BLE001 - Docker unavailable at startup must not crash app startup
        logger.warning("runtime_orphan_sweep_skipped", error=str(exc))
        return
    if code != 0:
        return
    container_ids = stdout.decode("utf-8", errors="replace").split()
    for container_id in container_ids:
        await run_docker("rm", "-f", container_id, timeout=10)
    if container_ids:
        logger.info("runtime_orphans_cleaned", count=len(container_ids))
