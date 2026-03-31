"""Unit tests for topology API router."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import FastAPI, status
from fastapi.testclient import TestClient

from src.domain.model.workspace.topology_edge import TopologyEdge
from src.domain.model.workspace.topology_node import TopologyNode, TopologyNodeType


def _make_node(node_id: str = "node-1") -> TopologyNode:
    return TopologyNode(
        id=node_id,
        workspace_id="ws-1",
        node_type=TopologyNodeType.NOTE,
        title="Node",
        position_x=10.0,
        position_y=20.0,
        hex_q=1,
        hex_r=-1,
        status="ready",
        tags=["alpha"],
        data={"a": 1},
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


def _make_edge(edge_id: str = "edge-1") -> TopologyEdge:
    return TopologyEdge(
        id=edge_id,
        workspace_id="ws-1",
        source_node_id="node-1",
        target_node_id="node-2",
        label="connects",
        source_hex_q=1,
        source_hex_r=-1,
        target_hex_q=2,
        target_hex_r=-1,
        direction="forward",
        auto_created=True,
        data={"w": 1},
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


@pytest.fixture
def mock_topology_service() -> AsyncMock:
    service = AsyncMock()
    service.create_node = AsyncMock(return_value=_make_node())
    service.list_nodes = AsyncMock(return_value=[_make_node()])
    service.list_all_nodes = AsyncMock(return_value=[_make_node()])
    service.get_node = AsyncMock(return_value=_make_node())
    service.update_node = AsyncMock(return_value=_make_node())
    service.list_edges_for_node = AsyncMock(return_value=[_make_edge()])
    service.delete_node = AsyncMock(return_value=True)

    service.create_edge = AsyncMock(return_value=_make_edge())
    service.list_edges = AsyncMock(return_value=[_make_edge()])
    service.list_all_edges = AsyncMock(return_value=[_make_edge()])
    service.get_edge = AsyncMock(return_value=_make_edge())
    service.update_edge = AsyncMock(return_value=_make_edge())
    service.delete_edge = AsyncMock(return_value=True)
    return service


@pytest.fixture
def topology_client(
    mock_topology_service: AsyncMock, monkeypatch: pytest.MonkeyPatch
) -> TestClient:
    from src.infrastructure.adapters.primary.web.dependencies import get_current_user
    from src.infrastructure.adapters.primary.web.routers.topology import (
        get_topology_service,
        router,
    )

    app = FastAPI()
    app.include_router(router)

    user = Mock()
    user.id = "user-1"
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_topology_service] = lambda: mock_topology_service
    publish_mock = AsyncMock()
    monkeypatch.setattr(
        "src.infrastructure.adapters.primary.web.routers.topology.publish_workspace_event_with_retry",
        publish_mock,
    )
    app.state.container = Mock()
    app.state.container.redis.return_value = Mock()
    client = TestClient(app)
    client.publish_mock = publish_mock  # type: ignore[attr-defined]
    return client


@pytest.mark.unit
class TestTopologyRouter:
    def test_create_node_success(
        self,
        topology_client: TestClient,
        mock_topology_service: AsyncMock,
    ) -> None:
        response = topology_client.post(
            "/api/v1/workspaces/ws-1/topology/nodes",
            json={
                "node_type": "note",
                "title": "My Node",
                "position_x": 12.5,
                "position_y": -3,
                "hex_q": 3,
                "hex_r": 1,
                "status": "queued",
                "tags": ["beta"],
                "data": {"foo": "bar"},
            },
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert response.json()["id"] == "node-1"
        assert response.json()["hex_q"] == 1
        assert response.json()["status"] == "ready"
        assert response.json()["tags"] == ["alpha"]
        assert mock_topology_service.create_node.await_count == 1
        assert mock_topology_service.create_node.await_args.kwargs["hex_q"] == 3
        assert mock_topology_service.create_node.await_args.kwargs["hex_r"] == 1
        assert mock_topology_service.create_node.await_args.kwargs["status"] == "queued"
        assert mock_topology_service.create_node.await_args.kwargs["tags"] == ["beta"]
        assert topology_client.publish_mock.await_count == 1  # type: ignore[attr-defined]

    def test_create_node_still_succeeds_when_event_publish_fails(
        self,
        topology_client: TestClient,
    ) -> None:
        topology_client.publish_mock.side_effect = RuntimeError("redis unavailable")  # type: ignore[attr-defined]

        response = topology_client.post(
            "/api/v1/workspaces/ws-1/topology/nodes",
            json={"node_type": "note", "title": "My Node"},
        )

        assert response.status_code == status.HTTP_201_CREATED

    def test_create_edge_success_uses_authoritative_endpoint_geometry(
        self,
        topology_client: TestClient,
        mock_topology_service: AsyncMock,
    ) -> None:
        response = topology_client.post(
            "/api/v1/workspaces/ws-1/topology/edges",
            json={
                "source_node_id": "node-1",
                "target_node_id": "node-2",
                "direction": "forward",
                "auto_created": True,
            },
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert response.json()["source_hex_q"] == 1
        assert response.json()["direction"] == "forward"
        assert response.json()["auto_created"] is True
        assert "source_hex_q" not in mock_topology_service.create_edge.await_args.kwargs
        assert "target_hex_q" not in mock_topology_service.create_edge.await_args.kwargs
        assert mock_topology_service.create_edge.await_args.kwargs["direction"] == "forward"
        assert mock_topology_service.create_edge.await_args.kwargs["auto_created"] is True

    def test_create_edge_rejects_client_controlled_geometry(self, topology_client: TestClient) -> None:
        response = topology_client.post(
            "/api/v1/workspaces/ws-1/topology/edges",
            json={
                "source_node_id": "node-1",
                "target_node_id": "node-2",
                "source_hex_q": 1,
            },
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    def test_create_node_validation_failure(self, topology_client: TestClient) -> None:
        response = topology_client.post(
            "/api/v1/workspaces/ws-1/topology/nodes",
            json={
                "node_type": "invalid-type",
                "title": "Bad Node",
            },
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    def test_create_node_rejects_out_of_bounds_hex(self, topology_client: TestClient) -> None:
        response = topology_client.post(
            "/api/v1/workspaces/ws-1/topology/nodes",
            json={
                "node_type": "note",
                "hex_q": 25,
                "hex_r": 0,
            },
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    def test_create_edge_permission_failure(
        self,
        topology_client: TestClient,
        mock_topology_service: AsyncMock,
    ) -> None:
        mock_topology_service.create_edge.side_effect = PermissionError("Insufficient permission")

        response = topology_client.post(
            "/api/v1/workspaces/ws-1/topology/edges",
            json={"source_node_id": "node-1", "target_node_id": "node-2"},
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert "permission" in response.json()["detail"].lower()

    def test_update_edge_workspace_validation_failure(
        self,
        topology_client: TestClient,
        mock_topology_service: AsyncMock,
    ) -> None:
        mock_topology_service.update_edge.side_effect = ValueError(
            "Endpoints must be in same workspace"
        )

        response = topology_client.patch(
            "/api/v1/workspaces/ws-1/topology/edges/edge-1",
            json={"source_node_id": "node-1", "target_node_id": "node-999"},
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "same workspace" in response.json()["detail"].lower()
