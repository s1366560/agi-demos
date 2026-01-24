import pytest
from fastapi import status
from httpx import AsyncClient

from src.infrastructure.adapters.primary.web.main import create_app

app = create_app()


@pytest.mark.asyncio
async def test_entity_type_crud(authenticated_async_client, test_project_db):
    client: AsyncClient = authenticated_async_client

    # Create
    create_resp = await client.post(
        f"/api/v1/projects/{test_project_db.id}/schema/entities",
        json={"name": "Person", "description": "Person entity", "schema_def": {"fields": []}},
    )
    assert create_resp.status_code == status.HTTP_200_OK
    entity = create_resp.json()
    entity_id = entity["id"]

    # List
    list_resp = await client.get(
        f"/api/v1/projects/{test_project_db.id}/schema/entities",
    )
    assert list_resp.status_code == status.HTTP_200_OK
    assert any(e["id"] == entity_id for e in list_resp.json())

    # Update
    update_resp = await client.put(
        f"/api/v1/projects/{test_project_db.id}/schema/entities/{entity_id}",
        json={"description": "Updated"},
    )
    assert update_resp.status_code == status.HTTP_200_OK
    assert update_resp.json()["description"] == "Updated"

    # Delete
    delete_resp = await client.delete(
        f"/api/v1/projects/{test_project_db.id}/schema/entities/{entity_id}",
    )
    assert delete_resp.status_code == status.HTTP_204_NO_CONTENT


@pytest.mark.asyncio
async def test_edge_type_crud(authenticated_async_client, test_project_db):
    client: AsyncClient = authenticated_async_client

    # Create
    create_resp = await client.post(
        f"/api/v1/projects/{test_project_db.id}/schema/edges",
        json={"name": "RELATES_TO", "description": "Relation", "schema_def": {"fields": []}},
    )
    assert create_resp.status_code == status.HTTP_200_OK
    edge = create_resp.json()
    edge_id = edge["id"]

    # List
    list_resp = await client.get(
        f"/api/v1/projects/{test_project_db.id}/schema/edges",
    )
    assert list_resp.status_code == status.HTTP_200_OK
    assert any(e["id"] == edge_id for e in list_resp.json())

    # Update
    update_resp = await client.put(
        f"/api/v1/projects/{test_project_db.id}/schema/edges/{edge_id}",
        json={"description": "Updated"},
    )
    assert update_resp.status_code == status.HTTP_200_OK
    assert update_resp.json()["description"] == "Updated"

    # Delete
    delete_resp = await client.delete(
        f"/api/v1/projects/{test_project_db.id}/schema/edges/{edge_id}",
    )
    assert delete_resp.status_code == status.HTTP_204_NO_CONTENT


@pytest.mark.asyncio
async def test_edge_map_crud(authenticated_async_client, test_project_db):
    client: AsyncClient = authenticated_async_client

    # Create mapping
    create_resp = await client.post(
        f"/api/v1/projects/{test_project_db.id}/schema/mappings",
        json={"source_type": "Person", "target_type": "Organization", "edge_type": "RELATES_TO"},
    )
    assert create_resp.status_code == status.HTTP_200_OK
    mapping = create_resp.json()
    map_id = mapping["id"]

    # List
    list_resp = await client.get(
        f"/api/v1/projects/{test_project_db.id}/schema/mappings",
    )
    assert list_resp.status_code == status.HTTP_200_OK
    assert any(m["id"] == map_id for m in list_resp.json())

    # Delete
    delete_resp = await client.delete(
        f"/api/v1/projects/{test_project_db.id}/schema/mappings/{map_id}",
    )
    assert delete_resp.status_code == status.HTTP_204_NO_CONTENT
