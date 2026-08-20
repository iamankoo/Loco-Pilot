"""Turns raw retrieval results into agent-consumable context.

Deduplicates repeated chunks, preserves file-path/chunk-boundary
information in a readable header per block, and enforces a hard character
budget so a large retrieval never blows out an agent's prompt.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from rag.retrieval.retriever import RetrievedChunk

DEFAULT_MAX_CONTEXT_CHARS = 12_000


class RepositoryContext(BaseModel):
    text: str
    chunks: list[RetrievedChunk] = Field(default_factory=list)
    truncated: bool = False


def build_context(chunks: list[RetrievedChunk], *, max_chars: int = DEFAULT_MAX_CONTEXT_CHARS) -> RepositoryContext:
    seen: set[tuple[str, int]] = set()
    parts: list[str] = []
    used: list[RetrievedChunk] = []
    total = 0
    truncated = False

    for chunk in chunks:
        key = (chunk.file_path, chunk.chunk_index)
        if key in seen:
            continue
        seen.add(key)

        header = f"--- {chunk.file_path} (chunk {chunk.chunk_index}, score={chunk.score:.3f}) ---\n"
        block = header + chunk.content.strip() + "\n"

        if total + len(block) > max_chars:
            remaining = max_chars - total
            if remaining > len(header) + 50:
                parts.append(block[:remaining] + "\n...<truncated>\n")
                used.append(chunk)
            truncated = True
            break

        parts.append(block)
        used.append(chunk)
        total += len(block)

    return RepositoryContext(text="".join(parts), chunks=used, truncated=truncated)
