"""Turns raw retrieval results into agent-consumable context.

Deduplicates repeated chunks, caps how many chunks from a single file may
dominate the budget, groups consecutive chunks from the same file under
one `[FILE N] path` label (with a per-chunk line-range sub-header) instead
of repeating the full header for every chunk, and enforces a hard
character budget so a large retrieval never blows out an agent's prompt.
Assumes the input list is already ordered by relevance (most relevant
first) — this module only assembles and bounds, it does not rank.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from rag.retrieval.retriever import RetrievedChunk

DEFAULT_MAX_CONTEXT_CHARS = 12_000
DEFAULT_MAX_CHUNKS_PER_FILE = 3


class RepositoryContext(BaseModel):
    text: str
    chunks: list[RetrievedChunk] = Field(default_factory=list)
    truncated: bool = False


def _line_range_label(chunk: RetrievedChunk) -> str:
    start = chunk.metadata.get("start_line")
    end = chunk.metadata.get("end_line")
    if start is not None and end is not None:
        return f"lines {start}-{end}"
    return f"chunk {chunk.chunk_index}"


def build_context(
    chunks: list[RetrievedChunk],
    *,
    max_chars: int = DEFAULT_MAX_CONTEXT_CHARS,
    max_chunks_per_file: int = DEFAULT_MAX_CHUNKS_PER_FILE,
) -> RepositoryContext:
    seen: set[tuple[str, int]] = set()
    per_file_count: dict[str, int] = {}
    file_labels: dict[str, int] = {}
    parts: list[str] = []
    used: list[RetrievedChunk] = []
    total = 0
    truncated = False
    previous_file_path: str | None = None

    for chunk in chunks:
        key = (chunk.file_path, chunk.chunk_index)
        if key in seen:
            continue
        if per_file_count.get(chunk.file_path, 0) >= max_chunks_per_file:
            # A selection choice (spend the budget across more files rather
            # than let one dominate it), not a hard truncation of the
            # overall retrieval — does not set `truncated`.
            continue
        seen.add(key)

        if chunk.file_path not in file_labels:
            file_labels[chunk.file_path] = len(file_labels) + 1
        is_new_block = chunk.file_path != previous_file_path

        line_label = f"{_line_range_label(chunk)} (score={chunk.score:.3f}):\n"
        header = f"[FILE {file_labels[chunk.file_path]}] {chunk.file_path}\n{line_label}" if is_new_block else line_label
        block = header + chunk.content.strip() + "\n\n"

        if total + len(block) > max_chars:
            remaining = max_chars - total
            if remaining > len(header) + 50:
                parts.append(block[:remaining] + "\n...<truncated>\n")
                used.append(chunk)
                per_file_count[chunk.file_path] = per_file_count.get(chunk.file_path, 0) + 1
            truncated = True
            break

        parts.append(block)
        used.append(chunk)
        per_file_count[chunk.file_path] = per_file_count.get(chunk.file_path, 0) + 1
        total += len(block)
        previous_file_path = chunk.file_path

    return RepositoryContext(text="".join(parts), chunks=used, truncated=truncated)
