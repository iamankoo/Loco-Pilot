"""Task-relevant file discovery: combines deterministic filename/path
keyword matching over the repository map with (optional) RAG semantic
retrieval evidence into one bounded, ranked list — never a request for the
LLM to blindly inspect the whole repository itself.
"""

from __future__ import annotations

import re

from pydantic import BaseModel

from analysis.scanner import RepositoryStructure

MAX_RELEVANT_FILES = 15

_STOPWORDS = {
    "a", "an", "the", "in", "of", "to", "for", "and", "is", "this", "that", "on", "with", "fix", "bug",
    "issue", "please", "add", "update", "from", "by", "at", "into", "make", "sure", "should", "there",
}


def _extract_keywords(task: str) -> set[str]:
    words = re.findall(r"[A-Za-z0-9]+", task.lower())
    keywords = {w for w in words if len(w) >= 3 and w not in _STOPWORDS}
    # A short prefix of each longer keyword catches common abbreviations
    # real codebases use (e.g. "auth" for "authentication") without a
    # hand-maintained synonym table.
    expanded = set(keywords)
    for word in keywords:
        if len(word) >= 6:
            expanded.add(word[:4])
    return expanded


def _score_path(path: str, keywords: set[str]) -> tuple[float, list[str]]:
    lower = path.lower()
    filename = lower.rsplit("/", 1)[-1]
    score = 0.0
    matched: list[str] = []
    for keyword in keywords:
        if keyword in filename:
            score += 2.0
            matched.append(keyword)
        elif keyword in lower:
            score += 1.0
            matched.append(keyword)
    return score, matched


class RelevantFile(BaseModel):
    path: str
    reason: str
    score: float


def find_relevant_files(
    structure: RepositoryStructure,
    task: str,
    *,
    retrieved_chunk_paths: list[tuple[str, float]] | None = None,
    max_results: int = MAX_RELEVANT_FILES,
) -> list[RelevantFile]:
    """`retrieved_chunk_paths` is `[(file_path, similarity_score), ...]` —
    already-retrieved RAG evidence (see `agents.graph`'s stage retrieval),
    passed in rather than re-queried here so this stays a pure function
    over data the caller already has."""
    keywords = _extract_keywords(task)
    scored: dict[str, RelevantFile] = {}

    for path in structure.files:
        score, matched = _score_path(path, keywords)
        if score > 0:
            scored[path] = RelevantFile(path=path, reason=f"path matches: {', '.join(sorted(set(matched)))}", score=score)

    for path, similarity in retrieved_chunk_paths or []:
        existing = scored.get(path)
        if existing is not None:
            scored[path] = RelevantFile(
                path=path, reason=existing.reason + "; retrieved by semantic search", score=existing.score + similarity
            )
        else:
            scored[path] = RelevantFile(path=path, reason="retrieved by semantic search", score=similarity)

    ranked = sorted(scored.values(), key=lambda item: item.score, reverse=True)
    return ranked[:max_results]
