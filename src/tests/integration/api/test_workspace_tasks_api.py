"""Integration tests for workspace task delegation API."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi import status
from httpx import AsyncClient

from src.application.services.workspace_task_event_publisher import (
    WorkspaceTaskEventPublisher,
)
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


@pytest.mark.asyncio
async def test_update_task_accepts_canonical_priority_strings(
    authenticated_async_client, test_db
) -> None:
    client: AsyncClient = authenticated_async_client

    user = User(
        id="550e8400-e29b-41d4-a716-446655440000",
        email="ws-api-priority@example.com",
        hashed_password="hash",
        full_name="Owner",
        is_active=True,
    )
    tenant = Tenant(
        id="tenant-ws-api-priority",
        name="TenantPriority",
        slug="tenant-ws-api-priority",
        description="tenant",
        owner_id=user.id,
        plan="free",
        max_projects=10,
        max_users=10,
        max_storage=1024,
    )
    project = Project(
        id="project-ws-api-priority",
        tenant_id=tenant.id,
        name="ProjectPriority",
        description="project",
        owner_id=user.id,
        memory_rules={},
        graph_config={},
    )
    workspace = WorkspaceModel(
        id="workspace-api-priority",
        tenant_id=tenant.id,
        project_id=project.id,
        name="Workspace Priority",
        created_by=user.id,
        metadata_json={},
    )
    membership = WorkspaceMemberModel(
        id="wm-api-priority",
        workspace_id=workspace.id,
        user_id=user.id,
        role="owner",
        invited_by=user.id,
    )
    task = WorkspaceTaskModel(
        id="task-api-priority",
        workspace_id=workspace.id,
        title="Task",
        created_by=user.id,
        status="todo",
        priority=0,
        metadata_json={},
        created_at=datetime.now(UTC),
    )
    user_tenant = UserTenant(
        id="ut-api-priority",
        user_id=user.id,
        tenant_id=tenant.id,
        role="owner",
        permissions={"admin": True, "read": True, "write": True},
    )
    user_project = UserProject(
        id="up-api-priority",
        user_id=user.id,
        project_id=project.id,
        role="owner",
    )

    test_db.add_all([user, tenant, project, workspace, membership, task, user_tenant, user_project])
    await test_db.commit()

    response = await client.patch(
        f"/api/v1/workspaces/{workspace.id}/tasks/{task.id}",
        json={"priority": "P3"},
    )

    assert response.status_code == status.HTTP_200_OK
    assert response.json()["priority"] == "P3"


@pytest.mark.asyncio
async def test_assign_agent_emits_full_task_payload_with_workspace_binding(
    authenticated_async_client,
    test_db,
    monkeypatch,
) -> None:
    client: AsyncClient = authenticated_async_client
    published_events: list[tuple[str, dict[str, object]]] = []

    async def _capture_pending_events(self, events) -> None:
        del self
        published_events.extend((event.event_type.value, event.payload) for event in events)

    monkeypatch.setattr(
        WorkspaceTaskEventPublisher,
        "publish_pending_events",
        _capture_pending_events,
    )

    user = User(
        id="550e8400-e29b-41d4-a716-446655440000",
        email="ws-api-owner4@example.com",
        hashed_password="hash",
        full_name="Owner",
        is_active=True,
    )
    tenant = Tenant(
        id="tenant-ws-api-4",
        name="Tenant4",
        slug="tenant-ws-api-4",
        description="tenant",
        owner_id=user.id,
        plan="free",
        max_projects=10,
        max_users=10,
        max_storage=1024,
    )
    project = Project(
        id="project-ws-api-4",
        tenant_id=tenant.id,
        name="Project4",
        description="project",
        owner_id=user.id,
        memory_rules={},
        graph_config={},
    )
    workspace = WorkspaceModel(
        id="workspace-api-5",
        tenant_id=tenant.id,
        project_id=project.id,
        name="Workspace E",
        created_by=user.id,
        metadata_json={},
    )
    membership = WorkspaceMemberModel(
        id="wm-api-5",
        workspace_id=workspace.id,
        user_id=user.id,
        role="owner",
        invited_by=user.id,
    )
    agent = AgentDefinitionModel(
        id="agent-api-5",
        tenant_id=tenant.id,
        project_id=project.id,
        name="agent-api-5",
        display_name="Agent API 5",
        system_prompt="You are an agent.",
        allowed_tools=[],
        allowed_skills=[],
        allowed_mcp_servers=[],
    )
    binding = WorkspaceAgentModel(
        id="wa-api-5",
        workspace_id=workspace.id,
        agent_id=agent.id,
        display_name="Agent API 5",
        description=None,
        config_json={},
        is_active=True,
    )
    task = WorkspaceTaskModel(
        id="task-api-5",
        workspace_id=workspace.id,
        title="Execution task",
        created_by=user.id,
        status="todo",
        metadata_json={
            "goal_evidence": {
                "goal_task_id": "root-5",
                "summary": "proof on ledger",
            }
        },
    )
    user_tenant = UserTenant(
        id="ut-api-5",
        user_id=user.id,
        tenant_id=tenant.id,
        role="owner",
        permissions={"admin": True, "read": True, "write": True},
    )
    user_project = UserProject(
        id="up-api-5",
        user_id=user.id,
        project_id=project.id,
        role="owner",
    )

    test_db.add_all(
        [user, tenant, project, workspace, membership, agent, binding, task, user_tenant, user_project]
    )
    await test_db.commit()

    response = await client.post(
        f"/api/v1/workspaces/{workspace.id}/tasks/{task.id}/assign-agent",
        json={"workspace_agent_id": binding.id},
    )

    assert response.status_code == status.HTTP_200_OK
    assigned_event = next(
        payload for event_type, payload in published_events if event_type == "workspace_task_assigned"
    )
    assert assigned_event["workspace_agent_id"] == binding.id
    assert assigned_event["assignee_agent_id"] == agent.id
    assert assigned_event["status"] == "todo"
    assert assigned_event["task"] == {
        "id": task.id,
        "workspace_id": workspace.id,
        "title": "Execution task",
        "description": None,
        "created_by": user.id,
        "assignee_user_id": None,
        "assignee_agent_id": agent.id,
        "status": "todo",
        "metadata": {
            "goal_evidence": {
                "goal_task_id": "root-5",
                "summary": "proof on ledger",
            }
        },
        "created_at": response.json()["created_at"],
        "updated_at": response.json()["updated_at"],
        "priority": "",
        "estimated_effort": None,
        "blocker_reason": None,
        "completed_at": None,
        "archived_at": None,
    }
