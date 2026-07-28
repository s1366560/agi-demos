"""Router tests for canonical Workspace Collaboration mutation authority."""

from __future__ import annotations

from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import FastAPI, status
from fastapi.testclient import TestClient

from src.application.services.workspace_collaboration_authority import (
    WorkspaceCollaborationMutationReceipt,
    WorkspaceCollaborationRevisionConflictError,
)

_BASE_PATH = "/api/v1/tenants/tenant-1/projects/project-1/workspaces/workspace-1/collaboration"


@pytest.fixture
def collaboration_router_client(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[TestClient, AsyncMock, AsyncMock]:
    from src.infrastructure.adapters.primary.web.dependencies import get_current_user
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
