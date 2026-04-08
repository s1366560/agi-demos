"""Unit tests for blackboard file route request scoping."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import FastAPI, status
from fastapi.testclient import TestClient

from src.infrastructure.adapters.primary.web.routers import blackboard as router_mod

TENANT_ID = "tenant-1"
PROJECT_ID = "project-1"
WORKSPACE_ID = "workspace-1"


@pytest.fixture
def blackboard_file_client(monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, Mock]:
    """Create a lightweight blackboard router client with mocked file service."""
    app = FastAPI()
    app.include_router(router_mod.router)

    async def _current_user() -> SimpleNamespace:
        return SimpleNamespace(id="user-1", email="user-1@example.com", display_name=None)

    async def _db():
        yield Mock()

    service = Mock()
    service.list_files = AsyncMock(return_value=[])
    service.read_file = AsyncMock(return_value=(b"hello", "text/plain"))

    app.dependency_overrides[router_mod.get_current_user] = _current_user
    app.dependency_overrides[router_mod.get_db] = _db
    monkeypatch.setattr(router_mod, "_file_service_from_request", lambda request, db: service)

    return TestClient(app), service


@pytest.mark.unit
def test_list_files_passes_current_user_to_service(
    blackboard_file_client: tuple[TestClient, Mock],
) -> None:
    """File listing should pass the authenticated user into the service layer."""
    client, service = blackboard_file_client

    response = client.get(
        f"/api/v1/tenants/{TENANT_ID}/projects/{PROJECT_ID}/workspaces/{WORKSPACE_ID}/blackboard/files"
    )

    assert response.status_code == status.HTTP_200_OK
    service.list_files.assert_awaited_once_with(
        tenant_id=TENANT_ID,
        project_id=PROJECT_ID,
        workspace_id=WORKSPACE_ID,
        actor_user_id="user-1",
        parent_path="/",
    )


@pytest.mark.unit
def test_download_file_passes_current_user_to_service(
    blackboard_file_client: tuple[TestClient, Mock],
) -> None:
    """File download should pass the authenticated user into the service layer."""
    client, service = blackboard_file_client

    response = client.get(
        f"/api/v1/tenants/{TENANT_ID}/projects/{PROJECT_ID}/workspaces/{WORKSPACE_ID}/blackboard/files/file-1/download"
    )

    assert response.status_code == status.HTTP_200_OK
    assert response.content == b"hello"
    service.read_file.assert_awaited_once_with(
        tenant_id=TENANT_ID,
        project_id=PROJECT_ID,
        workspace_id=WORKSPACE_ID,
        actor_user_id="user-1",
        file_id="file-1",
    )
