"""Line-based chunking with overlap.

Deliberately simple (no AST/tree-sitter parsing) — good enough to give the
retriever locality-preserving, line-numbered chunks within the 24-hour
build budget. Swapping in language-aware chunking later doesn't change
anything downstream (embedding, storage, retrieval all just consume
`Chunk.content`).
"""

from __future__ import annotations

from pydantic import BaseModel

DEFAULT_CHUNK_SIZE_LINES = 60
DEFAULT_OVERLAP_LINES = 10


class Chunk(BaseModel):
    content: str
    start_line: int
    end_line: int


def chunk_text(
    text: str,
    *,
    chunk_size_lines: int = DEFAULT_CHUNK_SIZE_LINES,
    overlap_lines: int = DEFAULT_OVERLAP_LINES,
) -> list[Chunk]:
    lines = text.splitlines()
    if not lines:
        return []

    chunks: list[Chunk] = []
    start = 0
    while start < len(lines):
        end = min(start + chunk_size_lines, len(lines))
        chunk_lines = lines[start:end]
        content = "\n".join(chunk_lines).strip()
        if content:
            chunks.append(Chunk(content=content, start_line=start + 1, end_line=end))
        if end == len(lines):
            break
        start = end - overlap_lines if end - overlap_lines > start else end

    return chunks
