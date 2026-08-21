"""Bounded unified-diff generation shared by every mutating filesystem
tool (`write_file`, `edit_file`, `delete_file`) — so a Developer/Debugger
tool call, and the persisted `ToolCall` record it produces, always carries
enough information to know exactly what changed, without ever handing an
entire large file to the LLM or to persistence.
"""

from __future__ import annotations

import difflib

from pydantic import BaseModel

MAX_DIFF_CHARS = 20_000


class FileDiff(BaseModel):
    diff: str
    truncated: bool


def compute_diff(path: str, before: str | None, after: str | None) -> FileDiff:
    """`before`/`after` are `None` for a file that didn't exist before the
    operation (creation) or doesn't exist after it (deletion) respectively.
    Identical content short-circuits to an empty, non-truncated diff."""
    if before == after:
        return FileDiff(diff="", truncated=False)

    before_lines = (before or "").splitlines(keepends=True)
    after_lines = (after or "").splitlines(keepends=True)
    from_label = "/dev/null" if before is None else path
    to_label = "/dev/null" if after is None else path

    text = "".join(difflib.unified_diff(before_lines, after_lines, fromfile=from_label, tofile=to_label))
    if len(text) > MAX_DIFF_CHARS:
        return FileDiff(diff=text[:MAX_DIFF_CHARS] + "\n...<diff truncated>\n", truncated=True)
    return FileDiff(diff=text, truncated=False)
