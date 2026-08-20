"""In-process cancellation signaling for running executions.

Deliberately not distributed — Phase 1 runs the whole graph inside one
FastAPI process (a background task), so a process-local set is the
correct scope, not a premature distributed-cancellation system. This does
not survive a process restart and does not coordinate across multiple
worker processes; a future multi-worker deployment would need a shared
signal (e.g. Redis), which the same call sites below can switch to
without changing any caller.

Granularity: checked between LangGraph node transitions (see
`agents.graph.make_agent_node`), not mid-tool-call — a command already
running inside a Docker sandbox completes before the next checkpoint
rather than being force-killed mid-execution. This is the practical scope
for Phase 1.5, not a gap introduced by oversight.
"""

from __future__ import annotations

import uuid

_cancelled: set[uuid.UUID] = set()


def request_cancellation(execution_id: uuid.UUID) -> None:
    _cancelled.add(execution_id)


def is_cancelled(execution_id: uuid.UUID) -> bool:
    return execution_id in _cancelled


def clear_cancellation(execution_id: uuid.UUID) -> None:
    _cancelled.discard(execution_id)
