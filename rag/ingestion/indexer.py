"""Repository indexing: File discovery -> Filtering -> Chunking -> Embedding -> pgvector.

Explicit and synchronous-per-call (`index_repository`) — no background file
watcher. Re-running against the same project re-indexes every discovered
file, and `replace_chunks_for_file` makes that idempotent per file, which
is the seed of incremental indexing without the complexity of tracking
content hashes yet.
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.logging import get_logger
from backend.app.db.repositories.repository_chunks import replace_chunks_for_file
from rag.chunking import chunk_text
from rag.embeddings.base import EmbeddingProvider
from rag.exclusions import MAX_INDEXABLE_FILE_BYTES, is_excluded_dir, is_supported_file
from rag.symbols import extract_symbols
from tools.workspace import Workspace

logger = get_logger(component="repository_indexer")


class IndexResult(BaseModel):
    files_indexed: int = 0
    files_skipped: int = 0
    chunks_created: int = 0


class RepositoryIndexer:
    def __init__(self, embedding_provider: EmbeddingProvider) -> None:
        self._embedding_provider = embedding_provider

    async def index_repository(
        self, workspace: Workspace, project_id: uuid.UUID, db: AsyncSession
    ) -> IndexResult:
        result = IndexResult()

        for file_path in self._discover_files(workspace.root):
            relative_path = workspace.relative(file_path)
            chunk_count = await self._index_one_file(workspace, project_id, relative_path, file_path, db)
            if chunk_count is None:
                result.files_skipped += 1
            else:
                result.files_indexed += 1
                result.chunks_created += chunk_count

        logger.info(
            "repository_indexed",
            project_id=str(project_id),
            files_indexed=result.files_indexed,
            files_skipped=result.files_skipped,
            chunks_created=result.chunks_created,
        )
        return result

    async def index_file(
        self, workspace: Workspace, project_id: uuid.UUID, relative_path: str, db: AsyncSession
    ) -> int:
        """Re-indexes exactly one file after it changes — the incremental
        path a Developer edit/write should trigger, instead of a full
        `index_repository` walk. Returns the number of chunks written (0 if
        the file is no longer indexable, e.g. deleted/binary/too large —
        `replace_chunks_for_file` still clears any stale chunks in that
        case, so nothing lingers for a file that no longer qualifies)."""
        file_path = workspace.resolve(relative_path)
        chunk_count = await self._index_one_file(workspace, project_id, relative_path, file_path, db)
        return chunk_count or 0

    async def _index_one_file(
        self,
        workspace: Workspace,
        project_id: uuid.UUID,
        relative_path: str,
        file_path: Path,
        db: AsyncSession,
    ) -> int | None:
        text = self._read_indexable_text(file_path)
        if text is None:
            await replace_chunks_for_file(db, project_id=project_id, file_path=relative_path, chunks=[])
            return None

        chunks = chunk_text(text)
        if not chunks:
            await replace_chunks_for_file(db, project_id=project_id, file_path=relative_path, chunks=[])
            return None

        embeddings = await self._embedding_provider.embed([c.content for c in chunks])
        extension = file_path.suffix
        chunk_rows = [
            {
                "chunk_index": i,
                "content": chunk.content,
                "embedding": embeddings[i],
                "metadata": {
                    "start_line": chunk.start_line,
                    "end_line": chunk.end_line,
                    "language": extension.lstrip("."),
                    # Bounded, best-effort function/class names for this
                    # chunk (see `rag/symbols.py`) — a retrieval signal,
                    # not a claim of correct parsing.
                    "symbols": extract_symbols(chunk.content, extension),
                },
            }
            for i, chunk in enumerate(chunks)
        ]
        await replace_chunks_for_file(db, project_id=project_id, file_path=relative_path, chunks=chunk_rows)
        return len(chunks)

    def _discover_files(self, root: Path):
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if not is_excluded_dir(d)]
            for filename in sorted(filenames):
                path = Path(dirpath) / filename
                if is_supported_file(path):
                    yield path

    def _read_indexable_text(self, file_path: Path) -> str | None:
        try:
            size = file_path.stat().st_size
            if size == 0 or size > MAX_INDEXABLE_FILE_BYTES:
                return None
            raw = file_path.read_bytes()
        except OSError:
            return None

        if b"\x00" in raw[:8000]:
            return None

        return raw.decode("utf-8", errors="replace")
