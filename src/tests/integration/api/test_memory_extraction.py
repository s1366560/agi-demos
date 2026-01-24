import pytest
from fastapi import status
from httpx import AsyncClient

from src.infrastructure.adapters.primary.web.main import create_app

app = create_app()


@pytest.mark.asyncio
async def test_extract_entities_with_content(authenticated_async_client):
    client: AsyncClient = authenticated_async_client
    resp = await client.post(
        "/api/v1/memories/extract-entities",
        json={"content": "Alice met Bob in Paris"},
    )
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()
    assert "entities" in data
    assert isinstance(data["entities"], list)


@pytest.mark.asyncio
async def test_extract_relationships_with_content(authenticated_async_client):
    client: AsyncClient = authenticated_async_client
    resp = await client.post(
        "/api/v1/memories/extract-relationships",
        json={"content": "Alice met Bob in Paris"},
    )
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()
    assert "relationships" in data
    assert isinstance(data["relationships"], list)
