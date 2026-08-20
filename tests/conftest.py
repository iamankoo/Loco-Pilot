from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from sqlalchemy import text

from tools.workspace import Workspace


@pytest.fixture
def tmp_workspace(tmp_path: Path) -> Workspace:
    return Workspace.at(tmp_path)


@pytest.fixture
def tmp_git_workspace(tmp_path: Path) -> Workspace:
    def _git(*args: str) -> None:
        subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True)

    _git("init", "-q")
    _git("config", "user.email", "test@example.com")
    _git("config", "user.name", "Test User")
    (tmp_path / "README.md").write_text("# Test repo\n", encoding="utf-8")
    _git("add", "README.md")
    _git("commit", "-q", "-m", "initial commit")
    return Workspace.at(tmp_path)


@pytest.fixture
async def db_session():
    """A real async DB session, skipping (not failing) when Postgres is unreachable."""
    from backend.app.db.session import get_engine, get_session_factory

    try:
        engine = get_engine()
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"PostgreSQL not reachable: {exc}")

    session_factory = get_session_factory()
    async with session_factory() as session:
        yield session


@pytest.fixture
async def client():
    """An httpx client against the real FastAPI app, for API-level tests
    that also need `db_session`/`tmp_workspace` from this conftest (the
    `client` fixture in backend/tests/conftest.py is not visible here —
    separate fixture trees)."""
    from httpx import ASGITransport, AsyncClient

    from backend.app.main import app as fastapi_app

    transport = ASGITransport(app=fastapi_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
