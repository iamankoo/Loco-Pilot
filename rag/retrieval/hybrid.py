"""Hybrid retrieval: re-ranks a wide semantic candidate pool using
deterministic keyword/path/symbol/test/explicit-file signals, rather than
trusting cosine similarity alone.

Why hybrid, not pure vector similarity: the default, dependency-free
embedding provider (`HashingEmbeddingProvider`) is NOT a real semantic
model — it is a deterministic hash projection, chosen so RAG works without
a paid API. Its cosine similarity is a weak relevance signal on its own.
Deterministic signals (does the path/filename mention the task's
keywords? does a chunk actually define the function being asked about? is
this an explicitly-named file?) give retrieval something dependable to
rank on regardless of which embedding provider is configured, and remain
additionally useful once a real semantic provider is in place too.

This intentionally reuses the existing single retrieval system
(`Retriever` + pgvector) rather than introducing a second one: hybrid
scoring only re-ranks a wider candidate pool that same call already
returns, plus (bounded, project-scoped) direct lookups for files named
explicitly in the task that the semantic pool might otherwise miss.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from analysis.relevant_files import extract_keywords, score_path
from analysis.scanner import is_test_path
from backend.app.core.logging import get_logger
from backend.app.db.repositories.repository_chunks import find_chunks_by_file_path_suffix
from rag.embeddings.base import EmbeddingProvider
from rag.retrieval.retriever import DEFAULT_TOP_K, RetrievedChunk, Retriever

logger = get_logger(component="hybrid_retrieval")

# How much wider than `top_k` the initial semantic candidate pool is —
# re-ranking needs headroom beyond the final result count to actually
# change the outcome, not just reorder an already-tiny set.
CANDIDATE_POOL_MULTIPLIER = 5
MIN_CANDIDATE_POOL = 40
MAX_EXPLICIT_FILE_HINTS = 5
EXPLICIT_HINT_CHUNKS_PER_FILE = 3

KEYWORD_SCORE_WEIGHT = 1.0
PATH_SCORE_WEIGHT = 1.0
SYMBOL_OVERLAP_WEIGHT = 1.5
# A whole identifier the query names verbatim (e.g. "fix authenticate_user"
# naming `def authenticate_user(...)`) is much stronger evidence than a
# mere decomposed-keyword overlap with a symbol name, so it gets its own,
# heavier weight rather than being folded into SYMBOL_OVERLAP_WEIGHT.
SYMBOL_EXACT_MATCH_WEIGHT = 4.0
TEST_BOOST = 1.5
EXPLICIT_FILE_BOOST = 5.0


@dataclass
class ScoredChunk:
    chunk: RetrievedChunk
    total_score: float
    reasons: list[str] = field(default_factory=list)


def _content_keyword_score(content: str, keywords: set[str]) -> float:
    if not keywords:
        return 0.0
    lowered = content.lower()
    return float(sum(1 for kw in keywords if kw in lowered))


def _symbol_overlap_score(symbols: list, keywords: set[str]) -> float:
    """How many symbols share a decomposed keyword with the query (e.g.
    query keywords {"refresh", "token"} against a `refresh_token` symbol)
    — a moderate signal, since a keyword substring match is common."""
    if not symbols or not keywords:
        return 0.0
    return float(sum(1 for symbol in symbols if any(kw in str(symbol).lower() for kw in keywords)))


def _symbol_exact_match_score(symbols: list, query_lower: str) -> float:
    """How many symbols are named verbatim, as a whole compound
    identifier, somewhere in the raw query text — much stronger evidence
    than a decomposed keyword overlap that this chunk is exactly what the
    query is asking about."""
    if not symbols or not query_lower:
        return 0.0
    return float(sum(1 for symbol in symbols if str(symbol) and str(symbol).lower() in query_lower))


class HybridRetriever:
    def __init__(self, embedding_provider: EmbeddingProvider) -> None:
        self._retriever = Retriever(embedding_provider)

    async def retrieve(
        self,
        query: str,
        *,
        project_id: uuid.UUID,
        db: AsyncSession,
        top_k: int = DEFAULT_TOP_K,
        explicit_file_hints: list[str] | None = None,
    ) -> list[RetrievedChunk]:
        candidate_k = max(top_k * CANDIDATE_POOL_MULTIPLIER, MIN_CANDIDATE_POOL)
        candidates = list(await self._retriever.retrieve(query, project_id=project_id, db=db, top_k=candidate_k))

        candidates = await self._augment_with_explicit_hints(candidates, explicit_file_hints, project_id=project_id, db=db)

        keywords = extract_keywords(query)
        query_lower = query.lower()
        scored = [self._score(chunk, keywords, query_lower, explicit_file_hints or []) for chunk in candidates]
        scored.sort(key=lambda s: s.total_score, reverse=True)
        top = scored[:top_k]

        logger.info(
            "hybrid_retrieval_completed",
            candidate_count=len(candidates),
            returned_count=len(top),
            top_score=top[0].total_score if top else 0.0,
            selected_files=[s.chunk.file_path for s in top],
        )
        return [
            s.chunk.model_copy(update={"retrieval_reason": "; ".join(s.reasons) if s.reasons else "semantic similarity"})
            for s in top
        ]

    async def _augment_with_explicit_hints(
        self,
        candidates: list[RetrievedChunk],
        explicit_file_hints: list[str] | None,
        *,
        project_id: uuid.UUID,
        db: AsyncSession,
    ) -> list[RetrievedChunk]:
        if not explicit_file_hints:
            return candidates

        present_paths = {c.file_path for c in candidates}
        augmented = list(candidates)
        for hint in explicit_file_hints[:MAX_EXPLICIT_FILE_HINTS]:
            if any(hint.lower() in path.lower() for path in present_paths):
                continue
            try:
                rows = await find_chunks_by_file_path_suffix(
                    db, project_id=project_id, suffix=hint, limit=EXPLICIT_HINT_CHUNKS_PER_FILE
                )
            except Exception as exc:  # noqa: BLE001 - an explicit-hint lookup failure must not break retrieval
                logger.warning("explicit_hint_lookup_failed", hint=hint, error=str(exc))
                continue
            for row in rows:
                augmented.append(
                    RetrievedChunk(
                        file_path=row.file_path,
                        content=row.content,
                        chunk_index=row.chunk_index,
                        score=0.0,
                        metadata=row.chunk_metadata or {},
                    )
                )
                present_paths.add(row.file_path)
        return augmented

    def _score(
        self, chunk: RetrievedChunk, keywords: set[str], query_lower: str, explicit_hints: list[str]
    ) -> ScoredChunk:
        reasons: list[str] = []
        path_score, path_matches = score_path(chunk.file_path, keywords)
        if path_matches:
            reasons.append(f"path matches: {', '.join(sorted(set(path_matches)))}")

        keyword_score = _content_keyword_score(chunk.content, keywords)
        if keyword_score:
            reasons.append(f"content keyword hits: {int(keyword_score)}")

        symbols = chunk.metadata.get("symbols") or []
        symbol_overlap = _symbol_overlap_score(symbols, keywords)
        symbol_exact = _symbol_exact_match_score(symbols, query_lower)
        if symbol_exact:
            reasons.append("defines a symbol named verbatim in the task")
        elif symbol_overlap:
            reasons.append("matches a defined symbol")

        test_relevant = path_score > 0 or keyword_score > 0 or symbol_overlap > 0 or symbol_exact > 0
        test_boost = TEST_BOOST if (test_relevant and is_test_path(chunk.file_path)) else 0.0
        if test_boost:
            reasons.append("test file relevant to this task")

        explicit_boost = 0.0
        if any(hint.lower() in chunk.file_path.lower() for hint in explicit_hints):
            explicit_boost = EXPLICIT_FILE_BOOST
            reasons.append("explicitly named in the task")

        total = (
            chunk.score
            + KEYWORD_SCORE_WEIGHT * keyword_score
            + PATH_SCORE_WEIGHT * path_score
            + SYMBOL_OVERLAP_WEIGHT * symbol_overlap
            + SYMBOL_EXACT_MATCH_WEIGHT * symbol_exact
            + test_boost
            + explicit_boost
        )
        return ScoredChunk(chunk=chunk, total_score=total, reasons=reasons)
