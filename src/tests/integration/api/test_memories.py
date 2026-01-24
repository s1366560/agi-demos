import pytest
from fastapi import status


@pytest.mark.asyncio
async def test_create_memory_invalid_data(authenticated_async_client):
    # authenticated_async_client uses test_app which overrides get_current_user

    response = await authenticated_async_client.post("/api/v1/memories/", json={})

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
