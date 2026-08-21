"""Phase 2.4 RAG evaluation fixture — a small, realistic repository with
clearly relevant and clearly unrelated files, used to verify that hybrid
retrieval ranking, project isolation, deduplication, context bounding,
test-awareness, filename-boosting, and symbol-matching all behave
correctly against real PostgreSQL/pgvector, real indexing, and real
retrieval (only the LLM is ever faked elsewhere in this suite — nothing
here needs one at all).
"""

from __future__ import annotations

import uuid

from backend.app.db.repositories.projects import create_project
from rag.embeddings.hashing_provider import HashingEmbeddingProvider
from rag.ingestion.indexer import RepositoryIndexer
from rag.retrieval.context_builder import build_context
from rag.retrieval.hybrid import HybridRetriever
from tools.workspace import Workspace


async def _build_sample_repository(workspace: Workspace, db_session) -> uuid.UUID:
    root = workspace.root
    (root / "auth").mkdir()
    (root / "payments").mkdir()
    (root / "users").mkdir()
    (root / "tests").mkdir()

    (root / "auth" / "jwt.py").write_text(
        "class JWTError(Exception):\n    pass\n\n"
        "def refresh_token(token: str) -> str:\n"
        '    """Issue a new JWT after validating the current refresh token."""\n'
        "    if not token:\n        raise JWTError('missing refresh token')\n"
        "    return encode_new_token(token)\n\n"
        "def decode_token(token: str) -> dict:\n"
        '    """Decode and validate a JWT, raising JWTError on failure."""\n'
        "    return {}\n",
        encoding="utf-8",
    )
    (root / "auth" / "session.py").write_text(
        "class SessionStore:\n    def __init__(self):\n        self.sessions = {}\n\n"
        "    def create_session(self, user_id):\n        self.sessions[user_id] = {}\n",
        encoding="utf-8",
    )
    (root / "auth" / "middleware.py").write_text(
        "def authenticate_request(request):\n"
        '    """Authenticate an incoming request using its bearer token."""\n'
        "    return True\n",
        encoding="utf-8",
    )

    (root / "payments" / "stripe.py").write_text(
        "def charge_card(amount, card_token):\n"
        '    """Charge a card via the Stripe API and return a receipt id."""\n'
        "    return 'receipt_123'\n",
        encoding="utf-8",
    )
    (root / "payments" / "invoice.py").write_text(
        "class Invoice:\n    def __init__(self, amount):\n        self.amount = amount\n\n"
        "def generate_invoice_pdf(invoice):\n"
        '    """Render an Invoice into a downloadable PDF document."""\n'
        "    return b''\n",
        encoding="utf-8",
    )

    (root / "users" / "profile.py").write_text(
        "def validate_profile(profile):\n"
        '    """Validate a user profile\'s required fields before saving."""\n'
        "    return not profile.get('name') is None\n",
        encoding="utf-8",
    )

    (root / "tests" / "test_auth.py").write_text(
        "def test_refresh_token_rejects_empty_token():\n"
        "    pass\n\n"
        "def test_authenticate_request_accepts_valid_bearer():\n"
        "    pass\n",
        encoding="utf-8",
    )
    (root / "tests" / "test_payments.py").write_text(
        "def test_charge_card_returns_receipt():\n    pass\n",
        encoding="utf-8",
    )

    (root / "README.md").write_text("# Sample project\nAn auth + payments + users demo.\n", encoding="utf-8")

    project = await create_project(db_session, name=f"eval-{uuid.uuid4()}", workspace_path=str(root))
    indexer = RepositoryIndexer(HashingEmbeddingProvider())
    await indexer.index_repository(workspace, project.id, db_session)
    return project.id


async def test_jwt_query_ranks_auth_files_above_unrelated_files(db_session, tmp_workspace: Workspace) -> None:
    project_id = await _build_sample_repository(tmp_workspace, db_session)
    retriever = HybridRetriever(HashingEmbeddingProvider())

    results = await retriever.retrieve("fix JWT refresh token bug", project_id=project_id, db=db_session, top_k=5)

    result_files = [r.file_path for r in results]
    assert result_files, "expected at least one result"
    assert result_files[0] == "auth/jwt.py"
    assert "payments/stripe.py" not in result_files[:2]


async def test_payment_query_ranks_payment_files_above_unrelated_files(db_session, tmp_workspace: Workspace) -> None:
    project_id = await _build_sample_repository(tmp_workspace, db_session)
    retriever = HybridRetriever(HashingEmbeddingProvider())

    results = await retriever.retrieve("payment invoice failure", project_id=project_id, db=db_session, top_k=5)

    result_files = [r.file_path for r in results]
    assert "payments/invoice.py" in result_files
    assert result_files.index("payments/invoice.py") < len(result_files) - 1 or len(result_files) == 1
    assert "users/profile.py" not in result_files[:1]


async def test_user_profile_query_ranks_profile_file_highly(db_session, tmp_workspace: Workspace) -> None:
    project_id = await _build_sample_repository(tmp_workspace, db_session)
    retriever = HybridRetriever(HashingEmbeddingProvider())

    results = await retriever.retrieve("user profile validation", project_id=project_id, db=db_session, top_k=5)

    result_files = [r.file_path for r in results]
    assert "users/profile.py" in result_files[:2]


async def test_explicit_symbol_name_surfaces_its_defining_chunk(db_session, tmp_workspace: Workspace) -> None:
    project_id = await _build_sample_repository(tmp_workspace, db_session)
    retriever = HybridRetriever(HashingEmbeddingProvider())

    results = await retriever.retrieve("fix authenticate_request bug", project_id=project_id, db=db_session, top_k=3)

    assert results[0].file_path == "auth/middleware.py"


async def test_test_files_are_boosted_when_relevant_but_not_blanket_retrieved(
    db_session, tmp_workspace: Workspace
) -> None:
    project_id = await _build_sample_repository(tmp_workspace, db_session)
    retriever = HybridRetriever(HashingEmbeddingProvider())

    results = await retriever.retrieve("fix refresh_token authentication bug", project_id=project_id, db=db_session, top_k=6)

    result_files = [r.file_path for r in results]
    assert "tests/test_auth.py" in result_files
    # The unrelated test file must not be dragged in just because it's a test.
    assert "tests/test_payments.py" not in result_files


async def test_explicit_filename_hint_boosts_a_weakly_similar_file(db_session, tmp_workspace: Workspace) -> None:
    project_id = await _build_sample_repository(tmp_workspace, db_session)
    retriever = HybridRetriever(HashingEmbeddingProvider())

    # A query with no real overlap with session.py's content — without the
    # explicit hint this file would not be expected to rank at all.
    results = await retriever.retrieve(
        "zzz nonsense query zzz",
        project_id=project_id,
        db=db_session,
        top_k=3,
        explicit_file_hints=["session.py"],
    )

    assert any(r.file_path == "auth/session.py" for r in results)


async def test_hybrid_retrieval_never_crosses_project_boundaries(db_session, tmp_workspace: Workspace, tmp_path) -> None:
    project_a = await _build_sample_repository(tmp_workspace, db_session)

    other_root = tmp_path / "project-b"
    other_root.mkdir()
    other_workspace = Workspace.at(other_root)
    (other_root / "unrelated.py").write_text("def totally_unrelated_marker(): pass\n", encoding="utf-8")
    project_b = await create_project(db_session, name=f"eval-b-{uuid.uuid4()}", workspace_path=str(other_root))
    await RepositoryIndexer(HashingEmbeddingProvider()).index_repository(other_workspace, project_b.id, db_session)

    retriever = HybridRetriever(HashingEmbeddingProvider())
    results = await retriever.retrieve(
        "fix JWT refresh token bug", project_id=project_a, db=db_session, top_k=10, explicit_file_hints=["jwt.py"]
    )

    assert all(r.file_path != "unrelated.py" for r in results)


async def test_hybrid_results_feed_into_a_bounded_deduplicated_context(db_session, tmp_workspace: Workspace) -> None:
    project_id = await _build_sample_repository(tmp_workspace, db_session)
    retriever = HybridRetriever(HashingEmbeddingProvider())

    results = await retriever.retrieve("fix JWT refresh token bug", project_id=project_id, db=db_session, top_k=8)
    context = build_context(results, max_chars=2_000)

    assert context.text
    assert len(context.text) <= 2_000 + 200
    assert "[FILE 1]" in context.text
    # No file path appears with a raw duplicate content block for the
    # exact same chunk index.
    seen = set()
    for chunk in context.chunks:
        key = (chunk.file_path, chunk.chunk_index)
        assert key not in seen
        seen.add(key)
