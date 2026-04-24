"""Tests for workspace chat router contract publishing."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

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
    WorkspaceModel,
)

TENANT_ID = "tenant-workspace-chat"
PROJECT_ID = "project-workspace-chat"
WORKSPACE_ID = "workspace-chat"
USER_ID = "550e8400-e29b-41d4-a716-446655440000"


async def _seed_workspace(test_db) -> None:
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
    test_db.add_all([tenant, project, workspace, user_tenant, user_project])
    await test_db.commit()


@pytest.mark.unit
class TestWorkspaceChatRouter:
    @pytest.mark.asyncio
    async def test_send_message_publishes_hosted_sensing_contract(
        self, test_db, client, test_user, monkeypatch
    ):
        publish_mock = AsyncMock()
        monkeypatch.setattr(
            "src.infrastructure.adapters.primary.web.routers.workspace_events.publish_workspace_event",
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
