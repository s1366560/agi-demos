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

    db = Mock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()

    async def _db():
        yield db

    service = Mock()
    service.list_files = AsyncMock(return_value=[])
    service.create_directory = AsyncMock()
    service.upload_file = AsyncMock()
    service.read_file = AsyncMock(return_value=(b"hello", "text/plain", "hello.txt"))
    service.delete_file = AsyncMock(return_value=True)
    service.db = db

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
    assert response.headers["content-disposition"] == "attachment; filename*=UTF-8''hello.txt"
    service.read_file.assert_awaited_once_with(
        tenant_id=TENANT_ID,
        project_id=PROJECT_ID,
        workspace_id=WORKSPACE_ID,
        actor_user_id="user-1",
        file_id="file-1",
    )


@pytest.mark.unit
def test_create_directory_passes_current_user_label_and_commits(
    blackboard_file_client: tuple[TestClient, Mock],
) -> None:
    """Directory creation should pass user identity and commit the scoped session."""
    client, service = blackboard_file_client
    service.create_directory.return_value = SimpleNamespace(
        id="dir-1",
        workspace_id=WORKSPACE_ID,
        parent_path="/",
        name="docs",
        is_directory=True,
        file_size=0,
        content_type="",
        uploader_type="user",
        uploader_id="user-1",
        uploader_name="user-1@example.com",
        created_at="2026-04-27T00:00:00Z",
    )

    response = client.post(
        f"/api/v1/tenants/{TENANT_ID}/projects/{PROJECT_ID}/workspaces/{WORKSPACE_ID}/blackboard/files/mkdir",
        json={"parent_path": "/", "name": "docs"},
    )

    assert response.status_code == status.HTTP_201_CREATED
    service.create_directory.assert_awaited_once_with(
        tenant_id=TENANT_ID,
        project_id=PROJECT_ID,
        workspace_id=WORKSPACE_ID,
        actor_user_id="user-1",
        actor_user_name="user-1@example.com",
        parent_path="/",
        name="docs",
    )
    service.db.commit.assert_awaited_once()


@pytest.mark.unit
def test_create_directory_rolls_back_on_service_error(
    blackboard_file_client: tuple[TestClient, Mock],
) -> None:
    """Failed file writes should roll back the request session."""
    client, service = blackboard_file_client
    service.create_directory.side_effect = ValueError("Invalid filename")

    response = client.post(
        f"/api/v1/tenants/{TENANT_ID}/projects/{PROJECT_ID}/workspaces/{WORKSPACE_ID}/blackboard/files/mkdir",
        json={"parent_path": "/", "name": "../docs"},
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    service.db.rollback.assert_awaited_once()


@pytest.mark.unit
def test_delete_file_commits_delete_result(
    blackboard_file_client: tuple[TestClient, Mock],
) -> None:
    """File deletion should commit after the service confirms deletion."""
    client, service = blackboard_file_client

    response = client.delete(
        f"/api/v1/tenants/{TENANT_ID}/projects/{PROJECT_ID}/workspaces/{WORKSPACE_ID}/blackboard/files/file-1"
    )

    assert response.status_code == status.HTTP_200_OK
    assert response.json() == {"deleted": True}
    service.delete_file.assert_awaited_once_with(
        tenant_id=TENANT_ID,
        project_id=PROJECT_ID,
        workspace_id=WORKSPACE_ID,
        actor_user_id="user-1",
        file_id="file-1",
    )
    service.db.commit.assert_awaited_once()
