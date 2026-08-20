from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from backend.app.main import app as fastapi_app


@pytest.fixture
async def client() -> AsyncClient:
    transport = ASGITransport(app=fastapi_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
