"""Sandbox network policy and resource limits.

Only `DISABLED` (the default) and `ALLOWED` are implemented — `RESTRICTED`
(egress limited to an allowlist) is reserved API surface for a later
milestone, not a half-built proxy now.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass


class NetworkPolicy(str, enum.Enum):
    DISABLED = "disabled"
    RESTRICTED = "restricted"
    ALLOWED = "allowed"


@dataclass(frozen=True)
class ResourceLimits:
    memory: str = "512m"
    cpus: str = "1.0"
    pids_limit: int = 128
    timeout_seconds: int = 60
    max_output_bytes: int = 500_000


@dataclass(frozen=True)
class PortPublish:
    """One container port published to the host, bound to loopback only
    (`127.0.0.1:<host_port>`) — never `0.0.0.0` — so a runtime started for
    localhost verification is reachable from this machine only, never from
    the network. The app inside the container must itself bind `0.0.0.0`
    (its own loopback is a different interface than the container's bridge
    endpoint Docker forwards the published port to) — this only governs
    the HOST-side exposure, which stays loopback-only regardless."""

    container_port: int
    host_port: int
