"""Integration tests for topology API endpoints."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi import status
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.adapters.secondary.persistence.models import (
    TopologyNodeModel,
    WorkspaceMemberModel,
    WorkspaceModel,
)

TEST_USER_ID = "550e8400-e29b-41d4-a716-446655440000"


@pytest.mark.asyncio
async def test_topology_nodes_happy_path(
    authenticated_async_client: AsyncClient,
    test_db: AsyncSession,
    test_tenant_db,
    test_project_db,
) -> None:
    workspace = WorkspaceModel(
        id="ws-topo-1",
        tenant_id=test_tenant_db.id,
        project_id=test_project_db.id,
        name="Topology Workspace 1",
        created_by=TEST_USER_ID,
        is_archived=False,
        metadata_json={},
    )
    member = WorkspaceMemberModel(
        id="wm-topo-1",
        workspace_id=workspace.id,
        user_id=TEST_USER_ID,
        role="editor",
        invited_by=TEST_USER_ID,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    test_db.add(workspace)
    test_db.add(member)
    await test_db.commit()

    create_resp = await authenticated_async_client.post(
        f"/api/v1/workspaces/{workspace.id}/topology/nodes",
        json={
            "node_type": "corridor",
            "title": "My Topology Node",
            "position_x": 10.5,
            "position_y": 20.25,
            "hex_q": 2,
            "hex_r": -1,
            "status": "ready",
            "tags": ["route", "alpha"],
            "data": {"color": "blue"},
        },
    )
    assert create_resp.status_code == status.HTTP_201_CREATED
    created = create_resp.json()
    assert created["workspace_id"] == workspace.id
    assert created["title"] == "My Topology Node"
    assert created["node_type"] == "corridor"
    assert created["hex_q"] == 2
    assert created["hex_r"] == -1
    assert created["status"] == "ready"
    assert created["tags"] == ["route", "alpha"]

    list_resp = await authenticated_async_client.get(
        f"/api/v1/workspaces/{workspace.id}/topology/nodes"
    )
    assert list_resp.status_code == status.HTTP_200_OK
    data = list_resp.json()
    assert len(data) >= 1


@pytest.mark.asyncio
async def test_topology_create_node_requires_membership(
    authenticated_async_client: AsyncClient,
    test_db: AsyncSession,
    test_tenant_db,
    test_project_db,
) -> None:
    workspace = WorkspaceModel(
        id="ws-topo-no-member",
        tenant_id=test_tenant_db.id,
        project_id=test_project_db.id,
        name="No Member Workspace",
        created_by=TEST_USER_ID,
        is_archived=False,
        metadata_json={},
    )
    test_db.add(workspace)
    await test_db.commit()

    response = await authenticated_async_client.post(
        f"/api/v1/workspaces/{workspace.id}/topology/nodes",
        json={"node_type": "note", "title": "Should Fail"},
    )
    assert response.status_code == status.HTTP_403_FORBIDDEN
    assert "member" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_topology_create_edge_rejects_cross_workspace_endpoints(
    authenticated_async_client: AsyncClient,
    test_db: AsyncSession,
    test_tenant_db,
    test_project_db,
) -> None:
    ws1 = WorkspaceModel(
        id="ws-topo-a",
        tenant_id=test_tenant_db.id,
        project_id=test_project_db.id,
        name="Workspace A",
        created_by=TEST_USER_ID,
        is_archived=False,
        metadata_json={},
    )
    ws2 = WorkspaceModel(
        id="ws-topo-b",
        tenant_id=test_tenant_db.id,
        project_id=test_project_db.id,
        name="Workspace B",
        created_by=TEST_USER_ID,
        is_archived=False,
        metadata_json={},
    )
    member = WorkspaceMemberModel(
        id="wm-topo-a",
        workspace_id=ws1.id,
        user_id=TEST_USER_ID,
        role="editor",
        invited_by=TEST_USER_ID,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    node_a = TopologyNodeModel(
        id="node-a",
        workspace_id=ws1.id,
        node_type="note",
        ref_id=None,
        title="Node A",
        position_x=0,
        position_y=0,
        data_json={},
    )
    node_b = TopologyNodeModel(
        id="node-b",
        workspace_id=ws2.id,
        node_type="note",
        ref_id=None,
        title="Node B",
        position_x=0,
        position_y=0,
        data_json={},
    )
    test_db.add_all([ws1, ws2, member, node_a, node_b])
    await test_db.commit()

    response = await authenticated_async_client.post(
        f"/api/v1/workspaces/{ws1.id}/topology/edges",
        json={"source_node_id": "node-a", "target_node_id": "node-b"},
    )
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "same workspace" in response.json()["detail"].lower()
