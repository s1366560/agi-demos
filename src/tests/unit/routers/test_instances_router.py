"""Unit tests for instance router tenant scoping."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import FastAPI, status
from fastapi.testclient import TestClient

from src.infrastructure.adapters.primary.web.routers import instances as router_mod


@pytest.fixture
def instances_client(monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, Mock]:
    """Create a lightweight client with mocked instance service."""
    app = FastAPI()
    app.include_router(router_mod.router)

    async def _tenant_id() -> str:
        return "tenant-1"

    async def _current_user() -> SimpleNamespace:
        return SimpleNamespace(id="user-1")

    async def _db():
        db = Mock()
        db.commit = AsyncMock()
        yield db

    service = Mock()
    service.create_instance = AsyncMock()
    service.get_instance = AsyncMock()
    service.update_config = AsyncMock()
    service.update_instance = AsyncMock()

    container = Mock()
    container.instance_service.return_value = service

    app.dependency_overrides[router_mod.get_current_user] = _current_user
    app.dependency_overrides[router_mod.get_current_user_tenant] = _tenant_id
    app.dependency_overrides[router_mod.get_db] = _db

    monkeypatch.setattr(router_mod, "get_container_with_db", lambda request, db: container)

    return TestClient(app), service


def _instance_response(**overrides: object) -> SimpleNamespace:
    """Build an object compatible with InstanceResponse.model_validate."""
    values = {
        "id": "inst-1",
        "name": "Agent Runtime",
        "slug": "agent-runtime",
        "description": None,
        "tenant_id": "tenant-1",
        "cluster_id": "cluster-1",
        "namespace": "agents",
        "image_version": "latest",
        "replicas": 1,
        "cpu_request": "100m",
        "cpu_limit": "500m",
        "mem_request": "256Mi",
        "mem_limit": "512Mi",
        "service_type": "ClusterIP",
        "ingress_domain": None,
        "env_vars": {},
        "quota_cpu": None,
        "quota_memory": None,
        "quota_max_pods": None,
        "storage_class": None,
        "storage_size": None,
        "advanced_config": {},
        "llm_providers": {},
        "compute_provider": None,
        "runtime": "default",
        "workspace_id": None,
        "hex_position_q": None,
        "hex_position_r": None,
        "agent_display_name": None,
        "agent_label": None,
        "theme_color": None,
        "status": "creating",
        "health_status": None,
        "current_revision": 0,
        "available_replicas": 0,
        "proxy_token": None,
        "pending_config": {},
        "created_by": "user-1",
        "created_at": datetime.now(UTC),
        "updated_at": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


@pytest.mark.unit
def test_create_instance_passes_extended_fields(
    instances_client: tuple[TestClient, Mock],
) -> None:
    """Create route must not drop UI-exposed deployment fields."""
    client, service = instances_client
    service.create_instance.return_value = _instance_response(
        quota_cpu="2",
        quota_memory="4Gi",
        quota_max_pods=5,
        storage_class="fast",
        storage_size="20Gi",
        compute_provider="kubernetes",
        runtime="docker",
        workspace_id="workspace-1",
        hex_position_q=2,
        hex_position_r=-1,
        agent_display_name="Runtime Agent",
        agent_label="prod",
        theme_color="#0070f3",
    )

    response = client.post(
        "/api/v1/instances/",
        json={
            "name": "Agent Runtime",
            "slug": "agent-runtime",
            "description": "Runs production agents",
            "tenant_id": "ignored-by-route",
            "cluster_id": "cluster-1",
            "namespace": "agents",
            "quota_cpu": "2",
            "quota_memory": "4Gi",
            "quota_max_pods": 5,
            "storage_class": "fast",
            "storage_size": "20Gi",
            "compute_provider": "kubernetes",
            "runtime": "docker",
            "workspace_id": "workspace-1",
            "hex_position_q": 2,
            "hex_position_r": -1,
            "agent_display_name": "Runtime Agent",
            "agent_label": "prod",
            "theme_color": "#0070f3",
        },
    )

    assert response.status_code == status.HTTP_201_CREATED
    kwargs = service.create_instance.await_args.kwargs
    assert kwargs["tenant_id"] == "tenant-1"
    assert kwargs["created_by"] == "user-1"
    assert kwargs["description"] == "Runs production agents"
    assert kwargs["quota_cpu"] == "2"
    assert kwargs["quota_memory"] == "4Gi"
    assert kwargs["quota_max_pods"] == 5
    assert kwargs["storage_class"] == "fast"
    assert kwargs["storage_size"] == "20Gi"
    assert kwargs["compute_provider"] == "kubernetes"
    assert kwargs["runtime"] == "docker"
    assert kwargs["workspace_id"] == "workspace-1"
    assert kwargs["hex_position_q"] == 2
    assert kwargs["hex_position_r"] == -1
    assert kwargs["agent_display_name"] == "Runtime Agent"
    assert kwargs["agent_label"] == "prod"
    assert kwargs["theme_color"] == "#0070f3"


@pytest.mark.unit
def test_update_instance_passes_extended_fields(
    instances_client: tuple[TestClient, Mock],
) -> None:
    """Update route must pass every mutable schema field to the service."""
    client, service = instances_client
    service.get_instance.return_value = _instance_response()
    service.update_instance.return_value = _instance_response(
        description="Updated runtime description",
        slug="renamed-runtime",
        cluster_id="cluster-2",
        namespace="runtime",
        quota_cpu="4",
        quota_memory="8Gi",
        quota_max_pods=10,
        storage_class="standard",
        storage_size="50Gi",
        compute_provider="local",
        runtime="kubernetes",
        workspace_id="workspace-2",
        hex_position_q=4,
        hex_position_r=3,
    )

    response = client.put(
        "/api/v1/instances/inst-1",
        json={
            "description": "Updated runtime description",
            "slug": "renamed-runtime",
            "cluster_id": "cluster-2",
            "namespace": "runtime",
            "quota_cpu": "4",
            "quota_memory": "8Gi",
            "quota_max_pods": 10,
            "storage_class": "standard",
            "storage_size": "50Gi",
            "compute_provider": "local",
            "runtime": "kubernetes",
            "workspace_id": "workspace-2",
            "hex_position_q": 4,
            "hex_position_r": 3,
        },
    )

    assert response.status_code == status.HTTP_200_OK
    kwargs = service.update_instance.await_args.kwargs
    assert kwargs["description"] == "Updated runtime description"
    assert kwargs["slug"] == "renamed-runtime"
    assert kwargs["cluster_id"] == "cluster-2"
    assert kwargs["namespace"] == "runtime"
    assert kwargs["quota_cpu"] == "4"
    assert kwargs["quota_memory"] == "8Gi"
    assert kwargs["quota_max_pods"] == 10
    assert kwargs["storage_class"] == "standard"
    assert kwargs["storage_size"] == "50Gi"
    assert kwargs["compute_provider"] == "local"
    assert kwargs["runtime"] == "kubernetes"
    assert kwargs["workspace_id"] == "workspace-2"
    assert kwargs["hex_position_q"] == 4
    assert kwargs["hex_position_r"] == 3


@pytest.mark.unit
def test_config_endpoints_return_not_found_for_other_tenant(
    instances_client: tuple[TestClient, Mock],
) -> None:
    """Config routes must not expose instances from another tenant."""
    client, service = instances_client
    service.get_instance.return_value = SimpleNamespace(
        id="inst-1",
        tenant_id="tenant-2",
        env_vars={"SECRET": "value"},
        advanced_config={},
        llm_providers={"provider_id": "other"},
    )

    get_response = client.get("/api/v1/instances/inst-1/config")
    assert get_response.status_code == status.HTTP_404_NOT_FOUND
    assert get_response.json()["detail"] == "Instance inst-1 not found"

    put_response = client.put(
        "/api/v1/instances/inst-1/config",
        json={"env_vars": {}, "advanced_config": {}, "llm_providers": {}},
    )
    assert put_response.status_code == status.HTTP_404_NOT_FOUND
    assert put_response.json()["detail"] == "Instance inst-1 not found"
    service.update_config.assert_not_awaited()


@pytest.mark.unit
def test_llm_config_endpoints_return_not_found_for_other_tenant(
    instances_client: tuple[TestClient, Mock],
) -> None:
    """LLM config routes must not expose instances from another tenant."""
    client, service = instances_client
    service.get_instance.return_value = SimpleNamespace(
        id="inst-1",
        tenant_id="tenant-2",
        llm_providers={"provider_id": "provider-1", "api_key_override": "secret"},
    )

    get_response = client.get("/api/v1/instances/inst-1/llm-config")
    assert get_response.status_code == status.HTTP_404_NOT_FOUND
    assert get_response.json()["detail"] == "Instance inst-1 not found"

    put_response = client.put(
        "/api/v1/instances/inst-1/llm-config",
        json={
            "provider_id": "provider-2",
            "model_name": "model-2",
            "api_key_override": "secret-2",
        },
    )
    assert put_response.status_code == status.HTTP_404_NOT_FOUND
    assert put_response.json()["detail"] == "Instance inst-1 not found"
    service.update_instance.assert_not_awaited()
