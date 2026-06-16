"""Tests for workspace chat router contract publishing."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import BackgroundTasks, HTTPException, status

from src.application.services.workspace_surface_contract import (
    HOSTED,
    NON_AUTHORITATIVE,
    SENSING_CAPABLE,
    SIGNAL_ROLE_KEY,
    SURFACE_BOUNDARY_KEY,
)
from src.infrastructure.adapters.secondary.persistence.models import (
    Project,
    Tenant,
    UserProject,
    UserTenant,
    WorkspaceMemberModel,
    WorkspaceModel,
)

TENANT_ID = "tenant-workspace-chat"
PROJECT_ID = "project-workspace-chat"
WORKSPACE_ID = "workspace-chat"
USER_ID = "550e8400-e29b-41d4-a716-446655440000"


async def _seed_workspace(test_db, *, workspace_role: str = "owner") -> None:
    tenant = Tenant(
        id=TENANT_ID,
        name="Workspace Chat Tenant",
        slug="workspace-chat-tenant",
        owner_id=USER_ID,
    )
    project = Project(
        id=PROJECT_ID,
        tenant_id=TENANT_ID,
        name="Workspace Chat Project",
        owner_id=USER_ID,
    )
    workspace = WorkspaceModel(
        id=WORKSPACE_ID,
        tenant_id=TENANT_ID,
        project_id=PROJECT_ID,
        name="Workspace Chat Workspace",
        created_by=USER_ID,
    )
    user_tenant = UserTenant(
        id="ut-workspace-chat",
        user_id=USER_ID,
        tenant_id=TENANT_ID,
        role="owner",
    )
    user_project = UserProject(
        id="up-workspace-chat",
        user_id=USER_ID,
        project_id=PROJECT_ID,
        role="owner",
    )
    workspace_member = WorkspaceMemberModel(
        id="wm-workspace-chat",
        workspace_id=WORKSPACE_ID,
        user_id=USER_ID,
        role=workspace_role,
        invited_by=USER_ID,
    )
    test_db.add_all([tenant, project, workspace, user_tenant, user_project, workspace_member])
    await test_db.commit()


@pytest.mark.unit
class TestWorkspaceChatRouter:
    def test_map_error_sanitizes_internal_errors(self):
        from src.infrastructure.adapters.primary.web.routers import workspace_chat

        exc = workspace_chat._map_error(RuntimeError("internal chat backend secret"))

        assert exc.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
        assert exc.detail == "Internal server error"
        assert "internal" not in exc.detail

    def test_map_error_sanitizes_permission_errors(self):
        from src.infrastructure.adapters.primary.web.routers import workspace_chat

        exc = workspace_chat._map_error(PermissionError("workspace chat secret denied"))

        assert exc.status_code == status.HTTP_403_FORBIDDEN
        assert exc.detail == "Access denied"

    def test_map_error_sanitizes_not_found_value_errors(self):
        from src.infrastructure.adapters.primary.web.routers import workspace_chat

        exc = workspace_chat._map_error(ValueError("message msg-secret not found"))

        assert exc.status_code == status.HTTP_404_NOT_FOUND
        assert exc.detail == "Workspace message not found"

    def test_map_error_sanitizes_bad_request_value_errors(self):
        from src.infrastructure.adapters.primary.web.routers import workspace_chat

        exc = workspace_chat._map_error(ValueError("secret message payload invalid"))

        assert exc.status_code == status.HTTP_400_BAD_REQUEST
        assert exc.detail == "Invalid workspace chat request"

    @pytest.mark.asyncio
    async def test_send_message_publishes_hosted_sensing_contract(
        self, test_db, client, test_user, monkeypatch
    ):
        publish_mock = AsyncMock()
        monkeypatch.setattr(
            "src.infrastructure.adapters.primary.web.routers.workspace_events."
            "publish_workspace_event_with_retry",
            publish_mock,
        )
        monkeypatch.setattr(client.app.state.container, "_redis_client", object(), raising=False)
        await _seed_workspace(test_db)

        response = client.post(
            f"/api/v1/tenants/{TENANT_ID}/projects/{PROJECT_ID}/workspaces/{WORKSPACE_ID}/messages",
            json={"content": "Hello Blackboard"},
        )

        assert response.status_code == 201
        payload = response.json()
        assert payload["workspace_id"] == WORKSPACE_ID
        assert payload["content"] == "Hello Blackboard"

        publish_kwargs = publish_mock.await_args.kwargs
        assert publish_kwargs["metadata"][SURFACE_BOUNDARY_KEY] == HOSTED
        assert publish_kwargs["metadata"]["authority_class"] == NON_AUTHORITATIVE
        assert publish_kwargs["metadata"][SIGNAL_ROLE_KEY] == SENSING_CAPABLE
        assert publish_kwargs["payload"][SURFACE_BOUNDARY_KEY] == HOSTED
        assert publish_kwargs["payload"][SIGNAL_ROLE_KEY] == SENSING_CAPABLE

    @pytest.mark.asyncio
    async def test_send_message_retries_publish_after_post_commit_failure(
        self, test_db, client, test_user, monkeypatch
    ):
        publish_mock = AsyncMock(side_effect=[RuntimeError("redis unavailable"), None])
        monkeypatch.setattr(
            "src.infrastructure.adapters.primary.web.routers.workspace_events."
            "publish_workspace_event_with_retry",
            publish_mock,
        )
        monkeypatch.setattr(client.app.state.container, "_redis_client", object(), raising=False)
        await _seed_workspace(test_db)

        response = client.post(
            f"/api/v1/tenants/{TENANT_ID}/projects/{PROJECT_ID}/workspaces/{WORKSPACE_ID}/messages",
            json={"content": "Hello after retry"},
        )

        assert response.status_code == 201
        assert response.json()["content"] == "Hello after retry"
        assert publish_mock.await_count == 2

    @pytest.mark.asyncio
    async def test_send_message_rejects_agent_sender_type(
        self, test_db, client, test_user, monkeypatch
    ):
        publish_mock = AsyncMock()
        monkeypatch.setattr(
            "src.infrastructure.adapters.primary.web.routers.workspace_events."
            "publish_workspace_event_with_retry",
            publish_mock,
        )
        await _seed_workspace(test_db)

        response = client.post(
            f"/api/v1/tenants/{TENANT_ID}/projects/{PROJECT_ID}/workspaces/{WORKSPACE_ID}/messages",
            json={"content": "Spoofed agent message", "sender_type": "agent"},
        )

        assert response.status_code == 400
        assert response.json()["detail"] == "Invalid workspace chat request"
        assert publish_mock.await_count == 0

    @pytest.mark.asyncio
    async def test_send_message_requires_workspace_editor(self, monkeypatch):
        from src.infrastructure.adapters.primary.web.routers import workspace_chat

        async def deny_without_editor(
            _db,
            _current_user,
            _tenant_id,
            _project_id,
            _workspace_id,
            *,
            require_editor: bool = False,
        ) -> None:
            assert require_editor is True
            raise HTTPException(status_code=403, detail="Workspace editor access required")

        monkeypatch.setattr(workspace_chat, "require_workspace_access", deny_without_editor)

        with pytest.raises(HTTPException) as exc_info:
            await workspace_chat.send_message(
                tenant_id=TENANT_ID,
                project_id=PROJECT_ID,
                workspace_id=WORKSPACE_ID,
                payload=workspace_chat.SendMessageRequest(content="Viewer write attempt"),
                request=SimpleNamespace(),
                background_tasks=BackgroundTasks(),
                current_user=SimpleNamespace(id=USER_ID, email="viewer@example.com"),
                db=AsyncMock(),
            )

        assert exc_info.value.status_code == 403
        assert exc_info.value.detail == "Workspace editor access required"
