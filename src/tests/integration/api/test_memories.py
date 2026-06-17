import pytest
from fastapi import status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.adapters.secondary.persistence.models import MemoryChunk


@pytest.mark.asyncio
async def test_create_memory_invalid_data(authenticated_async_client):
    # authenticated_async_client uses test_app which overrides get_current_user

    response = await authenticated_async_client.post("/api/v1/memories/", json={})

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


@pytest.mark.asyncio
async def test_create_memory_indexes_chunks(
    authenticated_async_client,
    test_project_db,
    db: AsyncSession,
):
    response = await authenticated_async_client.post(
        "/api/v1/memories/",
        json={
            "project_id": test_project_db.id,
            "title": "Chunked Memory",
            "content": "This memory should become searchable immediately.",
            "content_type": "text",
            "metadata": {"category": "fact"},
        },
    )

    assert response.status_code == status.HTTP_201_CREATED
    memory_id = response.json()["id"]

    result = await db.execute(
        select(MemoryChunk).where(
            MemoryChunk.project_id == test_project_db.id,
            MemoryChunk.source_type == "memory",
            MemoryChunk.source_id == memory_id,
        )
    )
    chunks = list(result.scalars().all())

    assert chunks
    assert all(chunk.category == "fact" for chunk in chunks)


@pytest.mark.asyncio
async def test_list_memories_filters_by_content_type(
    authenticated_async_client,
    test_project_db,
):
    for title, content_type in [
        ("Text Memory", "text"),
        ("Document Memory", "document"),
    ]:
        response = await authenticated_async_client.post(
            "/api/v1/memories/",
            json={
                "project_id": test_project_db.id,
                "title": title,
                "content": f"{title} body",
                "content_type": content_type,
            },
        )
        assert response.status_code == status.HTTP_201_CREATED

    response = await authenticated_async_client.get(
        "/api/v1/memories/",
        params={
            "project_id": test_project_db.id,
            "content_type": "document",
            "page": 1,
            "page_size": 10,
        },
    )

    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["total"] == 1
    assert [memory["content_type"] for memory in data["memories"]] == ["document"]
