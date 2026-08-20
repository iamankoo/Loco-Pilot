from __future__ import annotations

from httpx import AsyncClient


async def test_liveness(client: AsyncClient) -> None:
    response = await client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "locopilot-api"


async def test_readiness_reports_dependency_checks(client: AsyncClient) -> None:
    response = await client.get("/health/ready")
    assert response.status_code in (200, 503)
    body = response.json()
    assert "database" in body["checks"]
    assert "redis" in body["checks"]


async def test_api_v1_info(client: AsyncClient) -> None:
    response = await client.get("/api/v1/")
    assert response.status_code == 200
    assert response.json() == {"api_version": "v1", "status": "ok"}
