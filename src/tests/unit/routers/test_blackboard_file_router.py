"""Unit tests for blackboard file route request scoping."""

from __future__ import annotations

from collections.abc import AsyncIterator
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import FastAPI, Header, status
from fastapi.testclient import TestClient

from src.application.services.blackboard_file_service import BlackboardFileStream
from src.domain.model.workspace.actor_identity import ActorIdentity
from src.domain.model.workspace.blackboard_file import BlackboardFile
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
    db.flush = AsyncMock()
    db.add = Mock()

    async def _db():
        yield db

    service = Mock()
    service.list_files = AsyncMock(return_value=[])
    service.create_directory = AsyncMock()
    service.upload_file = AsyncMock()
    service.read_file = AsyncMock(return_value=(b"hello", "text/plain", "hello.txt"))

    async def _hello_iter() -> AsyncIterator[bytes]:
        yield b"hello"

    service.open_file_stream = AsyncMock(
        return_value=BlackboardFileStream(
            file_id="file-1",
            filename="hello.txt",
            content_type="text/plain",
            file_size=5,
            checksum_sha256=None,
            iterator=_hello_iter(),
        )
    )
    service.delete_file = AsyncMock(return_value=(True, False))
    service.db = db

    app.dependency_overrides[router_mod.get_current_user] = _current_user
    app.dependency_overrides[router_mod.get_db] = _db

    # Override the actor dep so it does not re-resolve via the real auth chain;
    # individual tests can replace this on the fly to simulate agent calls.
    async def _current_actor(
        x_agent_id: str | None = Header(default=None, alias="X-Agent-Id"),
        x_agent_label: str | None = Header(default=None, alias="X-Agent-Label"),
    ) -> ActorIdentity:
        if x_agent_id:
            return ActorIdentity(
                kind="agent",
                id=x_agent_id,
                label=x_agent_label or x_agent_id,
            )
        return ActorIdentity(kind="user", id="user-1", label="user-1@example.com")

    app.dependency_overrides[router_mod.get_current_actor] = _current_actor

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
    # Weak ETag fallback when checksum is missing.
    assert response.headers["etag"].startswith('W/"sz-5-id-file-1"')
    assert response.headers["accept-ranges"] == "bytes"
    service.open_file_stream.assert_awaited_once_with(
        tenant_id=TENANT_ID,
        project_id=PROJECT_ID,
        workspace_id=WORKSPACE_ID,
        actor_user_id="user-1",
        file_id="file-1",
    )


@pytest.mark.unit
def test_download_file_returns_strong_etag_when_checksum_known(
    blackboard_file_client: tuple[TestClient, Mock],
) -> None:
    """When checksum is persisted, download should advertise a strong ETag."""
    client, service = blackboard_file_client

    async def _iter() -> AsyncIterator[bytes]:
        yield b"hello"

    service.open_file_stream.return_value = BlackboardFileStream(
        file_id="file-1",
        filename="hello.txt",
        content_type="text/plain",
        file_size=5,
        checksum_sha256="a" * 64,
        iterator=_iter(),
    )

    response = client.get(
        f"/api/v1/tenants/{TENANT_ID}/projects/{PROJECT_ID}/workspaces/{WORKSPACE_ID}/blackboard/files/file-1/download"
    )

    assert response.status_code == status.HTTP_200_OK
    assert response.headers["etag"] == '"' + "a" * 64 + '"'


@pytest.mark.unit
def test_download_file_returns_304_when_if_none_match_matches(
    blackboard_file_client: tuple[TestClient, Mock],
) -> None:
    """Conditional GET with matching ETag should short-circuit to 304."""
    client, service = blackboard_file_client
    sha = "b" * 64

    async def _iter() -> AsyncIterator[bytes]:
        yield b"hello"

    service.open_file_stream.return_value = BlackboardFileStream(
        file_id="file-1",
        filename="hello.txt",
        content_type="text/plain",
        file_size=5,
        checksum_sha256=sha,
        iterator=_iter(),
    )

    response = client.get(
        f"/api/v1/tenants/{TENANT_ID}/projects/{PROJECT_ID}/workspaces/{WORKSPACE_ID}/blackboard/files/file-1/download",
        headers={"If-None-Match": f'"{sha}"'},
    )

    assert response.status_code == status.HTTP_304_NOT_MODIFIED
    assert response.headers["etag"] == f'"{sha}"'
    assert response.content == b""


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
        recursive=False,
    )
    service.db.commit.assert_awaited_once()


# =============================================================================
# Rename / Move / Copy router endpoints (M2 #C)
# =============================================================================


def _domain_file(**overrides: object) -> BlackboardFile:
    defaults: dict[str, object] = {
        "id": "file-1",
        "workspace_id": WORKSPACE_ID,
        "parent_path": "/",
        "name": "report.txt",
        "is_directory": False,
        "file_size": 10,
        "content_type": "text/plain",
        "storage_key": "file-1/report.txt",
        "uploader_type": "user",
        "uploader_id": "user-1",
        "uploader_name": "User One",
    }
    defaults.update(overrides)
    return BlackboardFile(**defaults)  # type: ignore[arg-type]


@pytest.mark.unit
def test_patch_file_requires_name_or_parent_path(
    blackboard_file_client: tuple[TestClient, Mock],
) -> None:
    client, service = blackboard_file_client
    response = client.patch(
        f"/api/v1/tenants/{TENANT_ID}/projects/{PROJECT_ID}/workspaces/{WORKSPACE_ID}/blackboard/files/file-1",
        json={},
    )
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    # Validation fires before the try/except; no rollback needed.
    service.db.commit.assert_not_awaited()


@pytest.mark.unit
def test_patch_file_renames(
    blackboard_file_client: tuple[TestClient, Mock],
) -> None:
    client, service = blackboard_file_client
    service.rename_file = AsyncMock(return_value=_domain_file(name="renamed.txt"))
    response = client.patch(
        f"/api/v1/tenants/{TENANT_ID}/projects/{PROJECT_ID}/workspaces/{WORKSPACE_ID}/blackboard/files/file-1",
        json={"name": "renamed.txt"},
    )
    assert response.status_code == status.HTTP_200_OK
    assert response.json()["name"] == "renamed.txt"
    service.rename_file.assert_awaited_once()
    service.db.commit.assert_awaited_once()


@pytest.mark.unit
def test_patch_file_moves(
    blackboard_file_client: tuple[TestClient, Mock],
) -> None:
    client, service = blackboard_file_client
    service.move_file = AsyncMock(
        return_value=_domain_file(parent_path="/archive/")
    )
    response = client.patch(
        f"/api/v1/tenants/{TENANT_ID}/projects/{PROJECT_ID}/workspaces/{WORKSPACE_ID}/blackboard/files/file-1",
        json={"parent_path": "/archive/"},
    )
    assert response.status_code == status.HTTP_200_OK
    assert response.json()["parent_path"] == "/archive/"
    service.move_file.assert_awaited_once()


@pytest.mark.unit
def test_copy_file_endpoint_returns_201(
    blackboard_file_client: tuple[TestClient, Mock],
) -> None:
    client, service = blackboard_file_client
    service.copy_file = AsyncMock(
        return_value=_domain_file(id="file-2", name="report-copy.txt")
    )
    response = client.post(
        f"/api/v1/tenants/{TENANT_ID}/projects/{PROJECT_ID}/workspaces/{WORKSPACE_ID}/blackboard/files/file-1/copy",
        json={"target_parent_path": "/", "name": "report-copy.txt"},
    )
    assert response.status_code == status.HTTP_201_CREATED
    body = response.json()
    assert body["id"] == "file-2"
    assert body["name"] == "report-copy.txt"
    service.copy_file.assert_awaited_once()


@pytest.mark.unit
def test_delete_recursive_flag_is_forwarded(
    blackboard_file_client: tuple[TestClient, Mock],
) -> None:
    client, service = blackboard_file_client
    service.delete_file = AsyncMock(return_value=(True, True))
    response = client.delete(
        f"/api/v1/tenants/{TENANT_ID}/projects/{PROJECT_ID}/workspaces/{WORKSPACE_ID}/blackboard/files/dir-1?recursive=true"
    )
    assert response.status_code == status.HTTP_200_OK
    call_kwargs = service.delete_file.await_args.kwargs
    assert call_kwargs["recursive"] is True
    assert call_kwargs["file_id"] == "dir-1"


# =============================================================================
# Agent upload provenance (M2 #B)
# =============================================================================


@pytest.mark.unit
def test_upload_as_user_passes_user_actor(
    blackboard_file_client: tuple[TestClient, Mock],
) -> None:
    client, service = blackboard_file_client
    service.upload_file = AsyncMock(return_value=_domain_file(name="hello.txt"))

    response = client.post(
        f"/api/v1/tenants/{TENANT_ID}/projects/{PROJECT_ID}/workspaces/{WORKSPACE_ID}/blackboard/files/upload",
        files={"file": ("hello.txt", b"data", "text/plain")},
        data={"parent_path": "/"},
    )
    assert response.status_code == status.HTTP_201_CREATED
    actor = service.upload_file.await_args.kwargs["actor"]
    assert actor.kind == "user"
    assert actor.id == "user-1"


@pytest.mark.unit
def test_upload_as_agent_passes_agent_actor(
    blackboard_file_client: tuple[TestClient, Mock],
) -> None:
    client, service = blackboard_file_client
    service.upload_file = AsyncMock(return_value=_domain_file(name="hello.txt"))

    response = client.post(
        f"/api/v1/tenants/{TENANT_ID}/projects/{PROJECT_ID}/workspaces/{WORKSPACE_ID}/blackboard/files/upload",
        files={"file": ("hello.txt", b"data", "text/plain")},
        data={"parent_path": "/"},
        headers={"X-Agent-Id": "researcher-007", "X-Agent-Label": "Researcher"},
    )
    assert response.status_code == status.HTTP_201_CREATED
    actor = service.upload_file.await_args.kwargs["actor"]
    assert actor.kind == "agent"
    assert actor.id == "researcher-007"
    assert actor.label == "Researcher"
