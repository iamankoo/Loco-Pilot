from __future__ import annotations

from rag.chunking import chunk_text


def test_empty_text_produces_no_chunks() -> None:
    assert chunk_text("") == []


def test_short_text_produces_one_chunk() -> None:
    text = "line1\nline2\nline3"
    chunks = chunk_text(text, chunk_size_lines=60, overlap_lines=10)
    assert len(chunks) == 1
    assert chunks[0].start_line == 1
    assert chunks[0].end_line == 3
    assert chunks[0].content == text


def test_long_text_splits_into_multiple_chunks() -> None:
    lines = [f"line{i}" for i in range(150)]
    text = "\n".join(lines)
    chunks = chunk_text(text, chunk_size_lines=60, overlap_lines=10)
    assert len(chunks) > 1
    assert chunks[0].start_line == 1
    assert chunks[0].end_line == 60


def test_chunks_overlap() -> None:
    lines = [f"line{i}" for i in range(150)]
    text = "\n".join(lines)
    chunks = chunk_text(text, chunk_size_lines=60, overlap_lines=10)
    # second chunk should start before the first chunk's end (overlap)
    assert chunks[1].start_line == chunks[0].end_line - 10 + 1


def test_chunking_covers_entire_file() -> None:
    lines = [f"line{i}" for i in range(200)]
    text = "\n".join(lines)
    chunks = chunk_text(text, chunk_size_lines=60, overlap_lines=10)
    assert chunks[-1].end_line == 200
