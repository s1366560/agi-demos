"""Unit tests for instance router tenant scoping."""

from __future__ import annotations

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
        yield Mock()

    service = Mock()
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
