from __future__ import annotations

from rag.retrieval.context_builder import build_context
from rag.retrieval.retriever import RetrievedChunk


def _chunk(path: str, index: int, content: str, score: float = 0.9) -> RetrievedChunk:
    return RetrievedChunk(file_path=path, chunk_index=index, content=content, score=score)


def test_build_context_includes_file_paths() -> None:
    context = build_context([_chunk("a.py", 0, "def foo(): pass")])
    assert "a.py" in context.text
    assert "def foo(): pass" in context.text


def test_build_context_deduplicates_same_chunk() -> None:
    chunk = _chunk("a.py", 0, "def foo(): pass")
    context = build_context([chunk, chunk])
    assert context.text.count("a.py") == 1
    assert len(context.chunks) == 1


def test_build_context_respects_max_chars() -> None:
    chunks = [_chunk(f"file{i}.py", 0, "x" * 500) for i in range(10)]
    context = build_context(chunks, max_chars=1000)
    assert len(context.text) <= 1000 + 200  # allow for headers/truncation marker
    assert context.truncated is True


def test_build_context_not_truncated_when_small() -> None:
    context = build_context([_chunk("a.py", 0, "small content")], max_chars=10_000)
    assert context.truncated is False


def test_build_context_empty_input() -> None:
    context = build_context([])
    assert context.text == ""
    assert context.chunks == []
    assert context.truncated is False
