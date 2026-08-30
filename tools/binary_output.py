"""Shared helpers for a controlled tool that writes a binary file into the
workspace — used by `tools/documents/tools.py` and `tools/image.py` so both
apply the identical workspace-boundary/overwrite/size-verification
discipline `tools/filesystem/tools.py`'s `write_file` already established,
without duplicating it a third time.
"""

from __future__ import annotations

from pathlib import Path

from tools.base import ToolContext, ToolError
from tools.workspace import WorkspaceError


def resolve_output_path(context: ToolContext, path: str, *, overwrite: bool) -> Path:
    try:
        target = context.workspace.resolve(path)
    except WorkspaceError as exc:
        raise ToolError(str(exc), code="PATH_OUTSIDE_WORKSPACE") from exc
    if target.exists():
        if target.is_dir():
            raise ToolError(f"Cannot write to a directory: {path}", code="INVALID_PATH")
        if not overwrite:
            raise ToolError(f"File already exists and overwrite=False: {path}", code="DESTINATION_EXISTS")
    target.parent.mkdir(parents=True, exist_ok=True)
    return target


def verify_written(target: Path, path: str, *, max_bytes: int) -> int:
    if not target.is_file():
        raise ToolError(f"Write verification failed: {path}")
    size = target.stat().st_size
    if size == 0:
        raise ToolError(f"Write verification failed (empty output): {path}")
    if size > max_bytes:
        target.unlink(missing_ok=True)
        raise ToolError(f"Generated file exceeds the maximum size of {max_bytes} bytes: {path}")
    return size
