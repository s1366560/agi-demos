import pytest
from fastapi import status
from httpx import AsyncClient
from sqlalchemy import select

from src.infrastructure.adapters.primary.web.main import create_app
from src.infrastructure.adapters.secondary.persistence.models import (
    EdgeType,
    EdgeTypeMap,
    EntityType,
    UserProject,
)

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


@pytest.mark.asyncio
async def test_viewer_can_list_but_cannot_mutate_schema(
    authenticated_async_client,
    db,
    test_project_db,
    test_user,
):
    client: AsyncClient = authenticated_async_client

    entity = EntityType(
        id="viewer_schema_entity",
        project_id=test_project_db.id,
        name="ViewerEntity",
        description="Original entity",
        schema={"fields": []},
    )
    edge = EdgeType(
        id="viewer_schema_edge",
        project_id=test_project_db.id,
        name="VIEWER_REL",
        description="Original edge",
        schema={"fields": []},
    )
    edge_map = EdgeTypeMap(
        id="viewer_schema_map",
        project_id=test_project_db.id,
        source_type="ViewerEntity",
        target_type="ViewerEntity",
        edge_type="VIEWER_REL",
    )
    db.add_all([entity, edge, edge_map])

    membership_result = await db.execute(
        select(UserProject).where(
            UserProject.user_id == test_user.id,
            UserProject.project_id == test_project_db.id,
        )
    )
    membership = membership_result.scalar_one()
    membership.role = "viewer"
    await db.commit()

    list_entities_resp = await client.get(f"/api/v1/projects/{test_project_db.id}/schema/entities")
    list_edges_resp = await client.get(f"/api/v1/projects/{test_project_db.id}/schema/edges")
    list_maps_resp = await client.get(f"/api/v1/projects/{test_project_db.id}/schema/mappings")

    assert list_entities_resp.status_code == status.HTTP_200_OK
    assert list_edges_resp.status_code == status.HTTP_200_OK
    assert list_maps_resp.status_code == status.HTTP_200_OK

    create_entity_resp = await client.post(
        f"/api/v1/projects/{test_project_db.id}/schema/entities",
        json={"name": "DeniedEntity", "description": "Denied", "schema_def": {"fields": []}},
    )
    update_entity_resp = await client.put(
        f"/api/v1/projects/{test_project_db.id}/schema/entities/{entity.id}",
        json={"description": "Denied update"},
    )
    delete_entity_resp = await client.delete(
        f"/api/v1/projects/{test_project_db.id}/schema/entities/{entity.id}",
    )
    create_edge_resp = await client.post(
        f"/api/v1/projects/{test_project_db.id}/schema/edges",
        json={"name": "DENIED_EDGE", "description": "Denied", "schema_def": {"fields": []}},
    )
    update_edge_resp = await client.put(
        f"/api/v1/projects/{test_project_db.id}/schema/edges/{edge.id}",
        json={"description": "Denied update"},
    )
    delete_edge_resp = await client.delete(
        f"/api/v1/projects/{test_project_db.id}/schema/edges/{edge.id}",
    )
    create_map_resp = await client.post(
        f"/api/v1/projects/{test_project_db.id}/schema/mappings",
        json={"source_type": "Denied", "target_type": "Denied", "edge_type": "DENIED_EDGE"},
    )
    delete_map_resp = await client.delete(
        f"/api/v1/projects/{test_project_db.id}/schema/mappings/{edge_map.id}",
    )

    assert create_entity_resp.status_code == status.HTTP_403_FORBIDDEN
    assert update_entity_resp.status_code == status.HTTP_403_FORBIDDEN
    assert delete_entity_resp.status_code == status.HTTP_403_FORBIDDEN
    assert create_edge_resp.status_code == status.HTTP_403_FORBIDDEN
    assert update_edge_resp.status_code == status.HTTP_403_FORBIDDEN
    assert delete_edge_resp.status_code == status.HTTP_403_FORBIDDEN
    assert create_map_resp.status_code == status.HTTP_403_FORBIDDEN
    assert delete_map_resp.status_code == status.HTTP_403_FORBIDDEN

    await db.refresh(entity)
    await db.refresh(edge)
    await db.refresh(edge_map)
    assert entity.description == "Original entity"
    assert edge.description == "Original edge"
