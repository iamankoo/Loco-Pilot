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
