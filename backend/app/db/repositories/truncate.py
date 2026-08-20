"""Guards against oversized values landing in JSONB audit columns.

Full tool output (e.g. a large file read) belongs in an Artifact pointing
at external/object storage in a later phase; this only keeps the
`tool_calls` audit trail bounded in size.
"""

from __future__ import annotations

MAX_STORED_FIELD_CHARS = 8_000


def truncate_for_storage(value: object, limit: int = MAX_STORED_FIELD_CHARS) -> object:
    if isinstance(value, str):
        if len(value) <= limit:
            return value
        return value[:limit] + f"...<truncated {len(value) - limit} chars>"
    if isinstance(value, dict):
        return {k: truncate_for_storage(v, limit) for k, v in value.items()}
    if isinstance(value, list):
        return [truncate_for_storage(v, limit) for v in value]
    return value
