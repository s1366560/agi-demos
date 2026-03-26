"""Integration tests for workspace task delegation API."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi import status
from httpx import AsyncClient

from src.infrastructure.adapters.secondary.persistence.models import (
    AgentDefinitionModel,
    Project,
    Tenant,
    User,
    UserProject,
    UserTenant,
    WorkspaceAgentModel,
    WorkspaceMemberModel,
    WorkspaceModel,
    WorkspaceTaskModel,
)


@pytest.mark.asyncio
async def test_assign_agent_rejects_cross_workspace_binding(authenticated_async_client, test_db) -> None:
    client: AsyncClient = authenticated_async_client

    user = User(
        id="550e8400-e29b-41d4-a716-446655440000",
        email="ws-api-owner@example.com",
        hashed_password="hash",
        full_name="Owner",
        is_active=True,
    )
    tenant = Tenant(
        id="tenant-ws-api",
        name="Tenant",
        slug="tenant-ws-api",
        description="tenant",
        owner_id=user.id,
        plan="free",
        max_projects=10,
        max_users=10,
        max_storage=1024,
    )
    project = Project(
        id="project-ws-api",
        tenant_id=tenant.id,
        name="Project",
        description="project",
        owner_id=user.id,
        memory_rules={},
        graph_config={},
    )
    workspace_1 = WorkspaceModel(
        id="workspace-api-1",
        tenant_id=tenant.id,
        project_id=project.id,
        name="Workspace A",
        created_by=user.id,
        metadata_json={},
    )
    workspace_2 = WorkspaceModel(
        id="workspace-api-2",
        tenant_id=tenant.id,
        project_id=project.id,
        name="Workspace B",
        created_by=user.id,
        metadata_json={},
    )
    membership = WorkspaceMemberModel(
        id="wm-api-1",
        workspace_id=workspace_1.id,
        user_id=user.id,
        role="owner",
        invited_by=user.id,
    )
    task = WorkspaceTaskModel(
        id="task-api-1",
        workspace_id=workspace_1.id,
        title="Task",
        created_by=user.id,
        status="todo",
        metadata_json={},
    )
    agent = AgentDefinitionModel(
        id="agent-api-1",
        tenant_id=tenant.id,
        project_id=project.id,
        name="agent-api-1",
        display_name="Agent API",
        system_prompt="You are an agent.",
        allowed_tools=[],
        allowed_skills=[],
        allowed_mcp_servers=[],
    )
    binding_wrong_workspace = WorkspaceAgentModel(
        id="wa-api-2",
        workspace_id=workspace_2.id,
        agent_id=agent.id,
        display_name="Agent API",
        description=None,
        config_json={},
        is_active=True,
    )
    user_tenant = UserTenant(
        id="ut-api-1",
        user_id=user.id,
        tenant_id=tenant.id,
        role="owner",
        permissions={"admin": True, "read": True, "write": True},
    )
    user_project = UserProject(
        id="up-api-1",
        user_id=user.id,
        project_id=project.id,
        role="owner",
    )

    test_db.add_all(
        [
            user,
            tenant,
            project,
            workspace_1,
            workspace_2,
            membership,
            task,
            agent,
            binding_wrong_workspace,
            user_tenant,
            user_project,
        ]
    )
    await test_db.commit()

    response = await client.post(
        f"/api/v1/workspaces/{workspace_1.id}/tasks/{task.id}/assign-agent",
        json={"workspace_agent_id": binding_wrong_workspace.id},
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "does not belong to workspace" in response.json()["detail"]


@pytest.mark.asyncio
async def test_state_transition_validation_for_complete(authenticated_async_client, test_db) -> None:
    client: AsyncClient = authenticated_async_client

    user = User(
        id="550e8400-e29b-41d4-a716-446655440000",
        email="ws-api-owner2@example.com",
        hashed_password="hash",
        full_name="Owner",
        is_active=True,
    )
    tenant = Tenant(
        id="tenant-ws-api-2",
        name="Tenant2",
        slug="tenant-ws-api-2",
        description="tenant",
        owner_id=user.id,
        plan="free",
        max_projects=10,
        max_users=10,
        max_storage=1024,
    )
    project = Project(
        id="project-ws-api-2",
        tenant_id=tenant.id,
        name="Project2",
        description="project",
        owner_id=user.id,
        memory_rules={},
        graph_config={},
    )
    workspace = WorkspaceModel(
        id="workspace-api-3",
        tenant_id=tenant.id,
        project_id=project.id,
        name="Workspace C",
        created_by=user.id,
        metadata_json={},
    )
    membership = WorkspaceMemberModel(
        id="wm-api-3",
        workspace_id=workspace.id,
        user_id=user.id,
        role="owner",
        invited_by=user.id,
    )
    task = WorkspaceTaskModel(
        id="task-api-3",
        workspace_id=workspace.id,
        title="Task",
        created_by=user.id,
        status="todo",
        metadata_json={},
        created_at=datetime.now(UTC),
    )
    user_tenant = UserTenant(
        id="ut-api-3",
        user_id=user.id,
        tenant_id=tenant.id,
        role="owner",
        permissions={"admin": True, "read": True, "write": True},
    )
    user_project = UserProject(
        id="up-api-3",
        user_id=user.id,
        project_id=project.id,
        role="owner",
    )

    test_db.add_all([user, tenant, project, workspace, membership, task, user_tenant, user_project])
    await test_db.commit()

    response = await client.post(f"/api/v1/workspaces/{workspace.id}/tasks/{task.id}/complete")
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "Cannot transition task status from todo to done" in response.json()["detail"]
