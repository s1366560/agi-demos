"""Router tests for canonical Workspace Collaboration mutation authority."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import FastAPI, HTTPException, status
from fastapi.testclient import TestClient
from starlette.requests import Request as StarletteRequest

from src.application.services.workspace_collaboration_authority import (
    WorkspaceCollaborationMutationReceipt,
    WorkspaceCollaborationRevisionConflictError,
)
from src.domain.model.workspace.actor_identity import ActorIdentity
from src.domain.model.workspace.blackboard_file import BlackboardFile

_BASE_PATH = "/api/v1/tenants/tenant-1/projects/project-1/workspaces/workspace-1/collaboration"


@pytest.fixture
def collaboration_router_client(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[TestClient, AsyncMock, AsyncMock]:
    from src.infrastructure.adapters.primary.web.dependencies import (
        get_current_actor,
        get_current_user,
    )
    from src.infrastructure.adapters.primary.web.routers import (
        workspace_collaboration_mutations as mutation_router,
    )
    from src.infrastructure.adapters.secondary.persistence.database import get_db

    app = FastAPI()
    app.include_router(
        mutation_router.router,
        prefix="/api/v1/tenants/{tenant_id}/projects/{project_id}/workspaces",
    )
    user = Mock(id="user-1")
    db = AsyncMock()
    service = AsyncMock()
    service.current_revision = AsyncMock(return_value=7)
    service.reserve = AsyncMock(
        return_value=WorkspaceCollaborationMutationReceipt(
            receipt_id="receipt-1",
            workspace_id="workspace-1",
            surface="discussion",
            action="create_post",
            expected_revision=7,
            revision=None,
            duplicate=False,
            dispatch_required=True,
        )
    )
    service.finalize = AsyncMock(
        return_value=WorkspaceCollaborationMutationReceipt(
            receipt_id="receipt-1",
            workspace_id="workspace-1",
            surface="discussion",
            action="create_post",
            expected_revision=7,
            revision=8,
            duplicate=False,
            dispatch_required=False,
        )
    )

    async def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_current_actor] = lambda: ActorIdentity(
        kind="user",
        id="user-1",
        label="Workspace User",
    )
    app.dependency_overrides[mutation_router.get_workspace_collaboration_mutation_service] = (
        lambda: service
    )
    monkeypatch.setattr(
        mutation_router,
        "require_workspace_access",
        AsyncMock(return_value=None),
    )
    dispatch = AsyncMock(return_value=None)
    monkeypatch.setattr(mutation_router, "_dispatch_mutation", dispatch)
    return TestClient(app), service, dispatch


@pytest.mark.unit
def test_workspace_collaboration_authority_is_scope_bound(
    collaboration_router_client: tuple[TestClient, AsyncMock, AsyncMock],
) -> None:
    client, service, _dispatch = collaboration_router_client

    response = client.get(f"{_BASE_PATH}/authority")

    assert response.status_code == status.HTTP_200_OK
    assert response.json() == {
        "contract_version": "2.0.0",
        "tenant_id": "tenant-1",
        "project_id": "project-1",
        "workspace_id": "workspace-1",
        "revision": 7,
        "cursor": "workspace:workspace-1:revision:7",
    }
    service.current_revision.assert_awaited_once()


@pytest.mark.unit
def test_workspace_collaboration_mutation_returns_committed_receipt(
    collaboration_router_client: tuple[TestClient, AsyncMock, AsyncMock],
) -> None:
    client, service, dispatch = collaboration_router_client

    response = client.post(
        f"{_BASE_PATH}/mutations",
        headers={
            "X-Expected-Revision": "7",
            "Idempotency-Key": "workspace-command-0001",
        },
        json={
            "contract_version": "2.0.0",
            "surface": "discussion",
            "action": "create_post",
            "expected_revision": 7,
            "idempotency_key": "workspace-command-0001",
            "payload": {"title": "Decision", "content": "Ship it"},
        },
    )

    assert response.status_code == status.HTTP_200_OK
    assert response.json() == {
        "contract_version": "2.0.0",
        "receipt_id": "receipt-1",
        "workspace_id": "workspace-1",
        "surface": "discussion",
        "action": "create_post",
        "revision": 8,
        "duplicate": False,
    }
    service.reserve.assert_awaited_once()
    dispatch.assert_awaited_once()
    service.finalize.assert_awaited_once()


@pytest.mark.unit
def test_workspace_collaboration_mutation_maps_stale_revision_to_conflict(
    collaboration_router_client: tuple[TestClient, AsyncMock, AsyncMock],
) -> None:
    client, service, dispatch = collaboration_router_client
    service.reserve.side_effect = WorkspaceCollaborationRevisionConflictError(
        expected_revision=7,
        current_revision=9,
    )

    response = client.post(
        f"{_BASE_PATH}/mutations",
        headers={
            "X-Expected-Revision": "7",
            "Idempotency-Key": "workspace-command-0001",
        },
        json={
            "contract_version": "2.0.0",
            "surface": "discussion",
            "action": "create_post",
            "expected_revision": 7,
            "idempotency_key": "workspace-command-0001",
            "payload": {"title": "Decision", "content": "Ship it"},
        },
    )

    assert response.status_code == status.HTTP_409_CONFLICT
    assert response.json()["detail"] == {
        "reason_code": "workspace_collaboration_revision_conflict",
        "message": "Workspace Collaboration mutation rejected",
        "expected_revision": 7,
        "current_revision": 9,
    }
    dispatch.assert_not_awaited()


@pytest.mark.unit
def test_workspace_upload_rejects_content_length_before_multipart_parsing(
    collaboration_router_client: tuple[TestClient, AsyncMock, AsyncMock],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.infrastructure.adapters.primary.web.routers import (
        workspace_collaboration_upload as upload_module,
    )

    client, service, _dispatch = collaboration_router_client
    monkeypatch.setattr(upload_module, "MAX_MULTIPART_REQUEST_BYTES", 32)

    response = client.post(
        f"{_BASE_PATH}/mutations/files/upload",
        headers={
            "Content-Type": "multipart/form-data; boundary=broken",
            "Content-Length": "33",
            "X-Expected-Revision": "7",
            "Idempotency-Key": "workspace-upload-0001",
        },
        content=b"not-a-valid-multipart-body",
    )

    assert response.status_code == status.HTTP_413_REQUEST_ENTITY_TOO_LARGE
    assert response.json()["detail"]["reason_code"] == "workspace_collaboration_upload_too_large"
    service.reserve.assert_not_awaited()


@pytest.mark.unit
def test_workspace_upload_stream_limit_cleans_staging_file(
    collaboration_router_client: tuple[TestClient, AsyncMock, AsyncMock],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from src.application.services import blackboard_file_service as file_service_module
    from src.infrastructure.adapters.primary.web.routers import (
        workspace_collaboration_upload as upload_module,
    )

    client, service, _dispatch = collaboration_router_client
    monkeypatch.setattr(file_service_module, "STORAGE_ROOT", tmp_path)
    monkeypatch.setattr(upload_module, "MAX_WORKSPACE_UPLOAD_BYTES", 4)
    monkeypatch.setattr(upload_module, "MAX_MULTIPART_REQUEST_BYTES", 4096)

    response = client.post(
        f"{_BASE_PATH}/mutations/files/upload",
        headers={
            "X-Expected-Revision": "7",
            "Idempotency-Key": "workspace-upload-0002",
        },
        data={"parent_path": "/"},
        files={"file": ("report.txt", b"12345", "text/plain")},
    )

    assert response.status_code == status.HTTP_413_REQUEST_ENTITY_TOO_LARGE
    assert response.json()["detail"]["reason_code"] == "workspace_collaboration_upload_too_large"
    service.reserve.assert_not_awaited()
    staging_root = tmp_path / ".staging"
    assert not staging_root.exists() or list(staging_root.iterdir()) == []


@pytest.mark.unit
def test_workspace_upload_hashes_bounded_stream_and_moves_staged_file(
    collaboration_router_client: tuple[TestClient, AsyncMock, AsyncMock],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from src.application.services import blackboard_file_service as file_service_module
    from src.infrastructure.adapters.primary.web.routers import (
        workspace_collaboration_mutations as mutation_router,
    )

    client, service, _dispatch = collaboration_router_client
    monkeypatch.setattr(file_service_module, "STORAGE_ROOT", tmp_path)
    persisted: dict[str, object] = {}

    async def reject_default_form_parser(*_args, **_kwargs):
        raise AssertionError("Workspace upload must not spool through Request.form()")

    monkeypatch.setattr(StarletteRequest, "form", reject_default_form_parser)

    async def persist_staged_file(**kwargs):
        staged_path = kwargs["staged_path"]
        persisted.update(kwargs)
        persisted["content"] = staged_path.read_bytes()
        staged_path.unlink()

    monkeypatch.setattr(
        mutation_router.blackboard,
        "upload_staged_file",
        AsyncMock(side_effect=persist_staged_file),
    )
    service.reserve.return_value = WorkspaceCollaborationMutationReceipt(
        receipt_id="upload-receipt",
        workspace_id="workspace-1",
        surface="files",
        action="upload_file",
        expected_revision=7,
        revision=None,
        duplicate=False,
        dispatch_required=True,
    )
    service.finalize.return_value = WorkspaceCollaborationMutationReceipt(
        receipt_id="upload-receipt",
        workspace_id="workspace-1",
        surface="files",
        action="upload_file",
        expected_revision=7,
        revision=8,
        duplicate=False,
        dispatch_required=False,
    )

    response = client.post(
        f"{_BASE_PATH}/mutations/files/upload",
        headers={
            "X-Expected-Revision": "7",
            "Idempotency-Key": "workspace-upload-0003",
        },
        data={"parent_path": "/docs"},
        files={"file": ("report.txt", b"bounded-content", "text/plain")},
    )

    assert response.status_code == status.HTTP_200_OK
    assert response.json()["revision"] == 8
    assert persisted["content"] == b"bounded-content"
    assert persisted["size_bytes"] == len(b"bounded-content")
    assert persisted["filename"] == "report.txt"
    staging_root = tmp_path / ".staging"
    assert not staging_root.exists() or list(staging_root.iterdir()) == []


@pytest.mark.unit
async def test_workspace_upload_bounds_stream_without_content_length(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.infrastructure.adapters.primary.web.routers import (
        workspace_collaboration_upload as upload_module,
    )

    body = b"--direct-boundary\r\n"
    delivered = False

    async def receive():
        nonlocal delivered
        if delivered:
            return {"type": "http.disconnect"}
        delivered = True
        return {"type": "http.request", "body": body, "more_body": False}

    request = StarletteRequest(
        {
            "type": "http",
            "method": "POST",
            "path": "/upload",
            "headers": [
                (
                    b"content-type",
                    b"multipart/form-data; boundary=direct-boundary",
                )
            ],
        },
        receive,
    )
    monkeypatch.setattr(upload_module, "MAX_MULTIPART_REQUEST_BYTES", len(body) - 1)

    with pytest.raises(HTTPException) as exc_info:
        await upload_module.stage_workspace_upload_request(request)

    assert exc_info.value.status_code == status.HTTP_413_REQUEST_ENTITY_TOO_LARGE
    assert exc_info.value.detail["reason_code"] == "workspace_collaboration_upload_too_large"


@pytest.mark.unit
async def test_workspace_upload_cancellation_cleans_partial_staging_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from src.application.services import blackboard_file_service as file_service_module
    from src.infrastructure.adapters.primary.web.routers import (
        workspace_collaboration_upload as upload_module,
    )

    monkeypatch.setattr(file_service_module, "STORAGE_ROOT", tmp_path)
    first_chunk = (
        b"--cancel-boundary\r\n"
        b'Content-Disposition: form-data; name="file"; filename="report.txt"\r\n'
        b"Content-Type: text/plain\r\n\r\n"
        b"partial-content"
    )
    delivered = False

    async def receive():
        nonlocal delivered
        if not delivered:
            delivered = True
            return {
                "type": "http.request",
                "body": first_chunk,
                "more_body": True,
            }
        raise asyncio.CancelledError

    request = StarletteRequest(
        {
            "type": "http",
            "method": "POST",
            "path": "/upload",
            "headers": [
                (
                    b"content-type",
                    b"multipart/form-data; boundary=cancel-boundary",
                )
            ],
        },
        receive,
    )

    with pytest.raises(asyncio.CancelledError):
        await upload_module.stage_workspace_upload_request(request)

    staging_root = tmp_path / ".staging"
    assert not staging_root.exists() or list(staging_root.iterdir()) == []


@pytest.mark.unit
@pytest.mark.parametrize(
    ("failure_stage", "failure"),
    [
        ("publish", RuntimeError("publish failed")),
        ("commit", RuntimeError("commit failed")),
        ("publish", asyncio.CancelledError()),
    ],
)
async def test_staged_upload_compensates_physical_file_when_transaction_does_not_complete(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    failure_stage: str,
    failure: BaseException,
) -> None:
    from src.infrastructure.adapters.primary.web.routers import blackboard

    uploaded = BlackboardFile(
        id="file-1",
        workspace_id="workspace-1",
        parent_path="/",
        name="report.txt",
        is_directory=False,
        file_size=7,
        content_type="text/plain",
        storage_key="file-1/report.txt",
        uploader_type="user",
        uploader_id="user-1",
        uploader_name="Workspace User",
        checksum_sha256="a" * 64,
    )
    service = Mock()
    service.upload_staged_file = AsyncMock(return_value=uploaded)
    service.discard_uploaded_file_storage = Mock()
    monkeypatch.setattr(
        blackboard,
        "_file_service_from_request",
        lambda _request, _db: service,
    )
    publish = AsyncMock()
    monkeypatch.setattr(blackboard, "publish_workspace_event", publish)
    db = AsyncMock()
    if failure_stage == "publish":
        publish.side_effect = failure
    else:
        db.commit.side_effect = failure

    expected_error = type(failure)
    if isinstance(failure, Exception):
        expected_error = HTTPException
    with pytest.raises(expected_error):
        await blackboard.upload_staged_file(
            tenant_id="tenant-1",
            project_id="project-1",
            workspace_id="workspace-1",
            request=Mock(),
            staged_path=tmp_path / "staged-upload",
            parent_path="/",
            filename="report.txt",
            size_bytes=7,
            checksum_sha256="a" * 64,
            current_user=Mock(id="user-1"),
            current_actor=ActorIdentity(
                kind="user",
                id="user-1",
                label="Workspace User",
            ),
            db=db,
        )

    db.rollback.assert_awaited_once()
    service.discard_uploaded_file_storage.assert_called_once_with(uploaded)


@pytest.mark.unit
async def test_staged_upload_does_not_delete_file_after_commit_wins_cancellation_race(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from src.infrastructure.adapters.primary.web.routers import blackboard

    uploaded = BlackboardFile(
        id="file-1",
        workspace_id="workspace-1",
        parent_path="/",
        name="report.txt",
        is_directory=False,
        file_size=7,
        content_type="text/plain",
        storage_key="file-1/report.txt",
        uploader_type="user",
        uploader_id="user-1",
        uploader_name="Workspace User",
        checksum_sha256="a" * 64,
    )
    service = Mock()
    service.upload_staged_file = AsyncMock(return_value=uploaded)
    service.discard_uploaded_file_storage = Mock()
    monkeypatch.setattr(
        blackboard,
        "_file_service_from_request",
        lambda _request, _db: service,
    )
    monkeypatch.setattr(
        blackboard,
        "publish_workspace_event",
        AsyncMock(),
    )
    commit_started = asyncio.Event()
    allow_commit = asyncio.Event()

    async def commit() -> None:
        commit_started.set()
        await allow_commit.wait()

    db = AsyncMock()
    db.commit.side_effect = commit
    upload_task = asyncio.create_task(
        blackboard.upload_staged_file(
            tenant_id="tenant-1",
            project_id="project-1",
            workspace_id="workspace-1",
            request=Mock(),
            staged_path=tmp_path / "staged-upload",
            parent_path="/",
            filename="report.txt",
            size_bytes=7,
            checksum_sha256="a" * 64,
            current_user=Mock(id="user-1"),
            current_actor=ActorIdentity(
                kind="user",
                id="user-1",
                label="Workspace User",
            ),
            db=db,
        )
    )
    await commit_started.wait()
    upload_task.cancel()
    allow_commit.set()

    with pytest.raises(asyncio.CancelledError):
        await upload_task

    db.rollback.assert_not_awaited()
    service.discard_uploaded_file_storage.assert_not_called()
