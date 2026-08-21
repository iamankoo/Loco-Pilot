"""Phase 2.10: per-project execution concurrency safety.

Two executions against the *same* project share one real workspace
directory on disk (see `execution_workspace.py`'s docstring for why that
directory is not duplicated per execution). Running two of them
concurrently would let their tool calls race on the same files — one
execution's `write_file` could be silently clobbered mid-edit by another's,
and Tester could run against a workspace neither execution actually
produced. Serializing executions per project_id is what makes "concurrent
execution safety" actually true for the architecture LocoPilot has today,
without introducing a second, duplicated workspace-management system.

Deliberately in-process only, same scope and rationale as
`cancellation.py`: Phase 1's single FastAPI worker process makes a
process-local lock sufficient; a future multi-worker deployment would need
a shared lock (e.g. a Postgres advisory lock or Redis), which callers here
could switch to without changing their own code.

Two different projects always run fully concurrently — this only ever
serializes executions that would otherwise touch the same files.
"""

from __future__ import annotations

import asyncio
import uuid

_project_locks: dict[uuid.UUID, asyncio.Lock] = {}


def get_project_execution_lock(project_id: uuid.UUID) -> asyncio.Lock:
    lock = _project_locks.get(project_id)
    if lock is None:
        lock = asyncio.Lock()
        _project_locks[project_id] = lock
    return lock
