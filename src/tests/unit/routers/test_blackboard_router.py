"""Tests for blackboard API router endpoints."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from src.application.services.workspace_surface_contract import (
    AUTHORITATIVE,
    OWNED,
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

TENANT_ID = "tenant-blackboard"
PROJECT_ID = "project-blackboard"
WORKSPACE_ID = "workspace-blackboard"
USER_ID = "550e8400-e29b-41d4-a716-446655440000"


async def _seed_workspace_membership(test_db, role: str = "editor") -> None:
    tenant = Tenant(
        id=TENANT_ID,
        name="Blackboard Tenant",
        slug="blackboard-tenant",
        owner_id=USER_ID,
    )
    project = Project(
        id=PROJECT_ID,
        tenant_id=TENANT_ID,
        name="Blackboard Project",
        owner_id=USER_ID,
    )
    workspace = WorkspaceModel(
        id=WORKSPACE_ID,
        tenant_id=TENANT_ID,
        project_id=PROJECT_ID,
        name="Blackboard Workspace",
        created_by=USER_ID,
    )
    user_tenant = UserTenant(
        id="ut-blackboard",
        user_id=USER_ID,
        tenant_id=TENANT_ID,
        role="owner",
    )
    user_project = UserProject(
        id="up-blackboard",
        user_id=USER_ID,
        project_id=PROJECT_ID,
        role="owner",
    )
    workspace_member = WorkspaceMemberModel(
        id="wm-blackboard",
        workspace_id=WORKSPACE_ID,
        user_id=USER_ID,
        role=role,
        invited_by=USER_ID,
    )
    test_db.add_all([tenant, project, workspace, user_tenant, user_project, workspace_member])
    await test_db.commit()


@pytest.mark.unit
class TestBlackboardRouter:
    @pytest.mark.asyncio
    async def test_create_and_list_posts(self, test_db, client, test_user, monkeypatch):
        publish_mock = AsyncMock()
        monkeypatch.setattr(
            "src.infrastructure.adapters.primary.web.routers.blackboard.publish_workspace_event",
            publish_mock,
        )
        await _seed_workspace_membership(test_db, role="editor")
        base = f"/api/v1/tenants/{TENANT_ID}/projects/{PROJECT_ID}/workspaces/{WORKSPACE_ID}/blackboard"

        create_response = client.post(
            f"{base}/posts",
            json={"title": "Release Plan", "content": "Ship by Friday"},
        )
        assert create_response.status_code == 201
        created = create_response.json()
        assert created["title"] == "Release Plan"
        assert created["is_pinned"] is False

        list_response = client.get(f"{base}/posts")
        assert list_response.status_code == 200
        payload = list_response.json()
        assert len(payload["items"]) == 1
        assert payload["items"][0]["id"] == created["id"]
        assert publish_mock.await_count == 1
        publish_kwargs = publish_mock.await_args.kwargs
        assert publish_kwargs["metadata"][SURFACE_BOUNDARY_KEY] == OWNED
        assert publish_kwargs["metadata"]["authority_class"] == AUTHORITATIVE
        assert publish_kwargs["metadata"][SIGNAL_ROLE_KEY] == SENSING_CAPABLE
        assert publish_kwargs["payload"][SURFACE_BOUNDARY_KEY] == OWNED
        assert publish_kwargs["payload"]["authority_class"] == AUTHORITATIVE

    @pytest.mark.asyncio
    async def test_viewer_cannot_create_but_can_list(self, test_db, client, test_user):
        await _seed_workspace_membership(test_db, role="viewer")
        base = f"/api/v1/tenants/{TENANT_ID}/projects/{PROJECT_ID}/workspaces/{WORKSPACE_ID}/blackboard"

        create_response = client.post(
            f"{base}/posts",
            json={"title": "Draft", "content": "Trying write access"},
        )
        assert create_response.status_code == 403

        list_response = client.get(f"{base}/posts")
        assert list_response.status_code == 200
        assert list_response.json()["items"] == []

    @pytest.mark.asyncio
    async def test_pin_and_reply_flow(self, test_db, client, test_user, monkeypatch):
        publish_mock = AsyncMock()
        monkeypatch.setattr(
            "src.infrastructure.adapters.primary.web.routers.blackboard.publish_workspace_event",
            publish_mock,
        )
        await _seed_workspace_membership(test_db, role="owner")
        base = f"/api/v1/tenants/{TENANT_ID}/projects/{PROJECT_ID}/workspaces/{WORKSPACE_ID}/blackboard"

        post_response = client.post(
            f"{base}/posts",
            json={"title": "Incident", "content": "Investigate root cause"},
        )
        post_id = post_response.json()["id"]

        pin_response = client.post(f"{base}/posts/{post_id}/pin")
        assert pin_response.status_code == 200
        assert pin_response.json()["is_pinned"] is True

        reply_response = client.post(
            f"{base}/posts/{post_id}/replies",
            json={"content": "Looking into logs now"},
        )
        assert reply_response.status_code == 201
        reply_id = reply_response.json()["id"]

        replies_response = client.get(f"{base}/posts/{post_id}/replies")
        assert replies_response.status_code == 200
        replies = replies_response.json()["items"]
        assert len(replies) == 1
        assert replies[0]["id"] == reply_id
        assert publish_mock.await_count >= 3
        for call in publish_mock.await_args_list:
            assert call.kwargs["metadata"][SURFACE_BOUNDARY_KEY] == OWNED
            assert call.kwargs["metadata"]["authority_class"] == AUTHORITATIVE
            assert call.kwargs["payload"][SURFACE_BOUNDARY_KEY] == OWNED
            assert call.kwargs["payload"]["authority_class"] == AUTHORITATIVE
