from __future__ import annotations

from httpx import AsyncClient


async def test_list_tools_endpoint(client: AsyncClient) -> None:
    response = await client.get("/api/v1/tools")
    assert response.status_code == 200

    tools = response.json()
    names = {t["name"] for t in tools}
    assert "read_file" in names
    assert "write_file" in names
    assert "git_status" in names
    assert all("input_schema" in t and "permission" in t for t in tools)
