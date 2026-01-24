import pytest
from fastapi import status


@pytest.mark.asyncio
async def test_create_project_invalid_data(authenticated_async_client):
    # Missing required fields
    response = await authenticated_async_client.post("/api/v1/projects/", json={})

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
