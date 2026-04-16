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
    BlackboardPostModel,
    CyberObjectiveModel,
    Project,
    Tenant,
    User,
    UserProject,
    UserTenant,
    WorkspaceAgentModel,
    WorkspaceMemberModel,
    WorkspaceMessageModel,
    WorkspaceModel,
    WorkspaceTaskModel,
)
from src.infrastructure.agent.workspace.workspace_goal_runtime import (
    should_activate_workspace_authority,
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
            },
            "last_mutation_actor": {
                "action": "assign_agent",
                "actor_type": "human",
                "actor_user_id": user.id,
                "actor_agent_id": agent.id,
                "workspace_agent_binding_id": binding.id,
                "reason": "workspace_task.assign_agent",
            },
        },
        "created_at": response.json()["created_at"],
        "updated_at": response.json()["updated_at"],
        "priority": "",
        "estimated_effort": None,
        "blocker_reason": None,
        "completed_at": None,
        "archived_at": None,
    }


@pytest.mark.asyncio
async def test_project_objective_to_root_task(authenticated_async_client, test_db) -> None:
    client: AsyncClient = authenticated_async_client

    user = User(
        id="550e8400-e29b-41d4-a716-446655440000",
        email="ws-api-objective@example.com",
        hashed_password="hash",
        full_name="Owner",
        is_active=True,
    )
    tenant = Tenant(
        id="tenant-ws-api-objective",
        name="TenantObjective",
        slug="tenant-ws-api-objective",
        description="tenant",
        owner_id=user.id,
        plan="free",
        max_projects=10,
        max_users=10,
        max_storage=1024,
    )
    project = Project(
        id="project-ws-api-objective",
        tenant_id=tenant.id,
        name="ProjectObjective",
        description="project",
        owner_id=user.id,
        memory_rules={},
        graph_config={},
    )
    workspace = WorkspaceModel(
        id="workspace-api-objective",
        tenant_id=tenant.id,
        project_id=project.id,
        name="Workspace Objective",
        created_by=user.id,
        metadata_json={},
    )
    membership = WorkspaceMemberModel(
        id="wm-api-objective",
        workspace_id=workspace.id,
        user_id=user.id,
        role="owner",
        invited_by=user.id,
    )
    objective = CyberObjectiveModel(
        id="obj-api-1",
        workspace_id=workspace.id,
        title="Ship rollback checklist",
        description="Make rollback deterministic",
        obj_type="objective",
        progress=0.5,
        created_by=user.id,
    )
    user_tenant = UserTenant(
        id="ut-api-objective",
        user_id=user.id,
        tenant_id=tenant.id,
        role="owner",
        permissions={"admin": True, "read": True, "write": True},
    )
    user_project = UserProject(
        id="up-api-objective",
        user_id=user.id,
        project_id=project.id,
        role="owner",
    )

    test_db.add_all(
        [user, tenant, project, workspace, membership, objective, user_tenant, user_project]
    )
    await test_db.commit()

    response = await client.post(
        f"/api/v1/tenants/{tenant.id}/projects/{project.id}/workspaces/{workspace.id}/objectives/{objective.id}/project-to-task"
    )

    assert response.status_code == status.HTTP_201_CREATED
    payload = response.json()
    assert payload["title"] == objective.title
    assert payload["metadata"]["task_role"] == "goal_root"
    assert payload["metadata"]["goal_origin"] == "existing_objective"
    assert payload["metadata"]["objective_id"] == objective.id
    assert payload["metadata"]["goal_source_refs"] == [f"objective:{objective.id}"]


@pytest.mark.asyncio
async def test_create_objective_auto_triggers_workspace_agent_execution(
    authenticated_async_client, test_db, monkeypatch
) -> None:
    client: AsyncClient = authenticated_async_client
    triggered: dict[str, object] = {}

    def _capture_fire(**kwargs: object) -> None:
        triggered.update(kwargs)

    monkeypatch.setattr(
        "src.infrastructure.adapters.primary.web.routers.cyber_objectives._fire_mention_routing",
        _capture_fire,
    )

    user = User(
        id="550e8400-e29b-41d4-a716-446655440000",
        email="ws-api-objective-trigger@example.com",
        hashed_password="hash",
        full_name="Owner",
        is_active=True,
    )
    tenant = Tenant(
        id="tenant-ws-api-objective-trigger",
        name="TenantObjectiveTrigger",
        slug="tenant-ws-api-objective-trigger",
        description="tenant",
        owner_id=user.id,
        plan="free",
        max_projects=10,
        max_users=10,
        max_storage=1024,
    )
    project = Project(
        id="project-ws-api-objective-trigger",
        tenant_id=tenant.id,
        name="ProjectObjectiveTrigger",
        description="project",
        owner_id=user.id,
        memory_rules={},
        graph_config={},
    )
    workspace = WorkspaceModel(
        id="workspace-api-objective-trigger",
        tenant_id=tenant.id,
        project_id=project.id,
        name="Workspace Objective Trigger",
        created_by=user.id,
        metadata_json={},
    )
    membership = WorkspaceMemberModel(
        id="wm-api-objective-trigger",
        workspace_id=workspace.id,
        user_id=user.id,
        role="owner",
        invited_by=user.id,
    )
    agent = AgentDefinitionModel(
        id="agent-api-objective-trigger",
        tenant_id=tenant.id,
        project_id=project.id,
        name="leader-agent",
        display_name="Leader Agent",
        system_prompt="You lead execution.",
        allowed_tools=[],
        allowed_skills=[],
        allowed_mcp_servers=[],
    )
    binding = WorkspaceAgentModel(
        id="wa-api-objective-trigger",
        workspace_id=workspace.id,
        agent_id=agent.id,
        display_name="Leader Agent",
        description=None,
        config_json={},
        is_active=True,
    )
    user_tenant = UserTenant(
        id="ut-api-objective-trigger",
        user_id=user.id,
        tenant_id=tenant.id,
        role="owner",
        permissions={"admin": True, "read": True, "write": True},
    )
    user_project = UserProject(
        id="up-api-objective-trigger",
        user_id=user.id,
        project_id=project.id,
        role="owner",
    )

    test_db.add_all(
        [user, tenant, project, workspace, membership, agent, binding, user_tenant, user_project]
    )
    await test_db.commit()

    response = await client.post(
        f"/api/v1/tenants/{tenant.id}/projects/{project.id}/workspaces/{workspace.id}/objectives",
        json={"title": "Ship browser test objective", "obj_type": "objective"},
    )

    assert response.status_code == status.HTTP_201_CREATED
    message = (
        await test_db.execute(
            WorkspaceMessageModel.__table__.select().where(
                WorkspaceMessageModel.workspace_id == workspace.id
            )
        )
    ).mappings().first()
    assert message is not None
    assert "@\"Leader Agent\"" in message["content"]
    assert "objective" in message["content"].lower()
    assert "workspace task" in message["content"].lower()
    assert should_activate_workspace_authority(message["content"]) is True
    assert triggered["workspace_id"] == workspace.id
    triggered_message = triggered["message"]
    assert triggered_message.mentions == [agent.id]
    assert triggered_message.metadata["conversation_scope"] == f"objective:{response.json()['id']}"


@pytest.mark.asyncio
async def test_update_rejects_immutable_human_root_goal_title_change(
    authenticated_async_client, test_db
) -> None:
    client: AsyncClient = authenticated_async_client

    user = User(
        id="550e8400-e29b-41d4-a716-446655440000",
        email="ws-api-root@example.com",
        hashed_password="hash",
        full_name="Owner",
        is_active=True,
    )
    tenant = Tenant(
        id="tenant-ws-api-root",
        name="TenantRoot",
        slug="tenant-ws-api-root",
        description="tenant",
        owner_id=user.id,
        plan="free",
        max_projects=10,
        max_users=10,
        max_storage=1024,
    )
    project = Project(
        id="project-ws-api-root",
        tenant_id=tenant.id,
        name="ProjectRoot",
        description="project",
        owner_id=user.id,
        memory_rules={},
        graph_config={},
    )
    workspace = WorkspaceModel(
        id="workspace-api-root",
        tenant_id=tenant.id,
        project_id=project.id,
        name="Workspace Root",
        created_by=user.id,
        metadata_json={},
    )
    membership = WorkspaceMemberModel(
        id="wm-api-root",
        workspace_id=workspace.id,
        user_id=user.id,
        role="owner",
        invited_by=user.id,
    )
    task = WorkspaceTaskModel(
        id="task-api-root",
        workspace_id=workspace.id,
        title="Human goal",
        description="Keep original wording",
        created_by=user.id,
        status="todo",
        metadata_json={
            "autonomy_schema_version": 1,
            "task_role": "goal_root",
            "goal_origin": "human_defined",
            "goal_source_refs": ["task:task-api-root"],
            "root_goal_policy": {
                "mutable_by_agent": False,
                "completion_requires_external_proof": True,
            },
        },
    )
    user_tenant = UserTenant(
        id="ut-api-root",
        user_id=user.id,
        tenant_id=tenant.id,
        role="owner",
        permissions={"admin": True, "read": True, "write": True},
    )
    user_project = UserProject(
        id="up-api-root",
        user_id=user.id,
        project_id=project.id,
        role="owner",
    )

    test_db.add_all([user, tenant, project, workspace, membership, task, user_tenant, user_project])
    await test_db.commit()

    response = await client.patch(
        f"/api/v1/workspaces/{workspace.id}/tasks/{task.id}",
        json={"title": "Mutated human goal"},
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "immutable root goal title" in response.json()["detail"]


@pytest.mark.asyncio
async def test_complete_rejects_inferred_root_goal_without_artifact_proof(
    authenticated_async_client, test_db
) -> None:
    client: AsyncClient = authenticated_async_client

    user = User(
        id="550e8400-e29b-41d4-a716-446655440000",
        email="ws-api-inferred@example.com",
        hashed_password="hash",
        full_name="Owner",
        is_active=True,
    )
    tenant = Tenant(
        id="tenant-ws-api-inferred",
        name="TenantInferred",
        slug="tenant-ws-api-inferred",
        description="tenant",
        owner_id=user.id,
        plan="free",
        max_projects=10,
        max_users=10,
        max_storage=1024,
    )
    project = Project(
        id="project-ws-api-inferred",
        tenant_id=tenant.id,
        name="ProjectInferred",
        description="project",
        owner_id=user.id,
        memory_rules={},
        graph_config={},
    )
    workspace = WorkspaceModel(
        id="workspace-api-inferred",
        tenant_id=tenant.id,
        project_id=project.id,
        name="Workspace Inferred",
        created_by=user.id,
        metadata_json={},
    )
    membership = WorkspaceMemberModel(
        id="wm-api-inferred",
        workspace_id=workspace.id,
        user_id=user.id,
        role="owner",
        invited_by=user.id,
    )
    task = WorkspaceTaskModel(
        id="task-api-inferred",
        workspace_id=workspace.id,
        title="Prepare rollback checklist",
        created_by=user.id,
        status="in_progress",
        metadata_json={
            "autonomy_schema_version": 1,
            "task_role": "goal_root",
            "goal_origin": "agent_inferred",
            "goal_source_refs": ["message:msg-1"],
            "goal_evidence_bundle": {
                "score": 0.85,
                "signals": [{"source_type": "message_signal", "ref": "message:msg-1", "score": 0.85}],
                "formalized_at": "2026-04-16T03:00:00Z",
            },
            "goal_evidence": {
                "goal_task_id": "task-api-inferred",
                "goal_text_snapshot": "Prepare rollback checklist",
                "outcome_status": "achieved",
                "summary": "Checklist drafted",
                "artifacts": [],
                "verifications": ["workspace_file_uploaded"],
                "generated_by_agent_id": "agent-7",
                "recorded_at": "2026-04-16T04:10:00Z",
                "verification_grade": "pass",
            },
        },
    )
    user_tenant = UserTenant(
        id="ut-api-inferred",
        user_id=user.id,
        tenant_id=tenant.id,
        role="owner",
        permissions={"admin": True, "read": True, "write": True},
    )
    user_project = UserProject(
        id="up-api-inferred",
        user_id=user.id,
        project_id=project.id,
        role="owner",
    )

    test_db.add_all([user, tenant, project, workspace, membership, task, user_tenant, user_project])
    await test_db.commit()

    response = await client.post(f"/api/v1/workspaces/{workspace.id}/tasks/{task.id}/complete")

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "proof artifacts before completion" in response.json()["detail"]


@pytest.mark.asyncio
async def test_patch_to_done_rejects_inferred_root_goal_without_artifact_proof(
    authenticated_async_client, test_db
) -> None:
    client: AsyncClient = authenticated_async_client

    user = User(
        id="550e8400-e29b-41d4-a716-446655440000",
        email="ws-api-inferred-patch@example.com",
        hashed_password="hash",
        full_name="Owner",
        is_active=True,
    )
    tenant = Tenant(
        id="tenant-ws-api-inferred-patch",
        name="TenantInferredPatch",
        slug="tenant-ws-api-inferred-patch",
        description="tenant",
        owner_id=user.id,
        plan="free",
        max_projects=10,
        max_users=10,
        max_storage=1024,
    )
    project = Project(
        id="project-ws-api-inferred-patch",
        tenant_id=tenant.id,
        name="ProjectInferredPatch",
        description="project",
        owner_id=user.id,
        memory_rules={},
        graph_config={},
    )
    workspace = WorkspaceModel(
        id="workspace-api-inferred-patch",
        tenant_id=tenant.id,
        project_id=project.id,
        name="Workspace Inferred Patch",
        created_by=user.id,
        metadata_json={},
    )
    membership = WorkspaceMemberModel(
        id="wm-api-inferred-patch",
        workspace_id=workspace.id,
        user_id=user.id,
        role="owner",
        invited_by=user.id,
    )
    task = WorkspaceTaskModel(
        id="task-api-inferred-patch",
        workspace_id=workspace.id,
        title="Prepare rollback checklist",
        created_by=user.id,
        status="in_progress",
        metadata_json={
            "autonomy_schema_version": 1,
            "task_role": "goal_root",
            "goal_origin": "agent_inferred",
            "goal_source_refs": ["message:msg-1"],
            "goal_evidence_bundle": {
                "score": 0.85,
                "signals": [{"source_type": "message_signal", "ref": "message:msg-1", "score": 0.85}],
                "formalized_at": "2026-04-16T03:00:00Z",
            },
            "goal_evidence": {
                "goal_task_id": "task-api-inferred-patch",
                "goal_text_snapshot": "Prepare rollback checklist",
                "outcome_status": "achieved",
                "summary": "Checklist drafted",
                "artifacts": [],
                "verifications": ["workspace_file_uploaded"],
                "generated_by_agent_id": "agent-7",
                "recorded_at": "2026-04-16T04:10:00Z",
                "verification_grade": "pass",
            },
        },
    )
    user_tenant = UserTenant(
        id="ut-api-inferred-patch",
        user_id=user.id,
        tenant_id=tenant.id,
        role="owner",
        permissions={"admin": True, "read": True, "write": True},
    )
    user_project = UserProject(
        id="up-api-inferred-patch",
        user_id=user.id,
        project_id=project.id,
        role="owner",
    )

    test_db.add_all([user, tenant, project, workspace, membership, task, user_tenant, user_project])
    await test_db.commit()

    response = await client.patch(
        f"/api/v1/workspaces/{workspace.id}/tasks/{task.id}",
        json={"status": "done"},
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "proof artifacts before completion" in response.json()["detail"]


@pytest.mark.asyncio
async def test_project_objective_to_existing_task_requires_membership(
    authenticated_async_client, test_db
) -> None:
    client: AsyncClient = authenticated_async_client

    owner = User(
        id="550e8400-e29b-41d4-a716-446655440020",
        email="ws-api-objective-owner@example.com",
        hashed_password="hash",
        full_name="Owner",
        is_active=True,
    )
    outsider = User(
        id="550e8400-e29b-41d4-a716-446655440000",
        email="ws-api-objective-outsider@example.com",
        hashed_password="hash",
        full_name="Outsider",
        is_active=True,
    )
    tenant = Tenant(
        id="tenant-ws-api-objective-auth",
        name="TenantObjectiveAuth",
        slug="tenant-ws-api-objective-auth",
        description="tenant",
        owner_id=owner.id,
        plan="free",
        max_projects=10,
        max_users=10,
        max_storage=1024,
    )
    project = Project(
        id="project-ws-api-objective-auth",
        tenant_id=tenant.id,
        name="ProjectObjectiveAuth",
        description="project",
        owner_id=owner.id,
        memory_rules={},
        graph_config={},
    )
    workspace = WorkspaceModel(
        id="workspace-api-objective-auth",
        tenant_id=tenant.id,
        project_id=project.id,
        name="Workspace Objective Auth",
        created_by=owner.id,
        metadata_json={},
    )
    owner_membership = WorkspaceMemberModel(
        id="wm-api-objective-owner",
        workspace_id=workspace.id,
        user_id=owner.id,
        role="owner",
        invited_by=owner.id,
    )
    objective = CyberObjectiveModel(
        id="obj-api-auth",
        workspace_id=workspace.id,
        title="Ship rollback checklist",
        description="Make rollback deterministic",
        obj_type="objective",
        progress=0.5,
        created_by=owner.id,
    )
    projected_task = WorkspaceTaskModel(
        id="task-api-objective-auth",
        workspace_id=workspace.id,
        title=objective.title,
        created_by=owner.id,
        status="todo",
        metadata_json={
            "autonomy_schema_version": 1,
            "task_role": "goal_root",
            "goal_origin": "existing_objective",
            "goal_source_refs": [f"objective:{objective.id}"],
            "objective_id": objective.id,
            "root_goal_policy": {
                "mutable_by_agent": False,
                "completion_requires_external_proof": True,
            },
        },
    )
    owner_tenant = UserTenant(
        id="ut-api-objective-owner",
        user_id=owner.id,
        tenant_id=tenant.id,
        role="owner",
        permissions={"admin": True, "read": True, "write": True},
    )
    owner_project = UserProject(
        id="up-api-objective-owner",
        user_id=owner.id,
        project_id=project.id,
        role="owner",
    )
    outsider_tenant = UserTenant(
        id="ut-api-objective-outsider",
        user_id=outsider.id,
        tenant_id=tenant.id,
        role="owner",
        permissions={"admin": True, "read": True, "write": True},
    )
    outsider_project = UserProject(
        id="up-api-objective-outsider",
        user_id=outsider.id,
        project_id=project.id,
        role="owner",
    )

    test_db.add_all(
        [
            owner,
            outsider,
            tenant,
            project,
            workspace,
            owner_membership,
            objective,
            projected_task,
            owner_tenant,
            owner_project,
            outsider_tenant,
            outsider_project,
        ]
    )
    await test_db.commit()

    response = await client.post(
        f"/api/v1/tenants/{tenant.id}/projects/{project.id}/workspaces/{workspace.id}/objectives/{objective.id}/project-to-task"
    )

    assert response.status_code == status.HTTP_403_FORBIDDEN
    assert "workspace member" in response.json()["detail"]


@pytest.mark.asyncio
async def test_list_workspace_goal_candidates(authenticated_async_client, test_db) -> None:
    client: AsyncClient = authenticated_async_client

    user = User(
        id="550e8400-e29b-41d4-a716-446655440000",
        email="ws-api-candidates@example.com",
        hashed_password="hash",
        full_name="Owner",
        is_active=True,
    )
    tenant = Tenant(
        id="tenant-ws-api-candidates",
        name="TenantCandidates",
        slug="tenant-ws-api-candidates",
        description="tenant",
        owner_id=user.id,
        plan="free",
        max_projects=10,
        max_users=10,
        max_storage=1024,
    )
    project = Project(
        id="project-ws-api-candidates",
        tenant_id=tenant.id,
        name="ProjectCandidates",
        description="project",
        owner_id=user.id,
        memory_rules={},
        graph_config={},
    )
    workspace = WorkspaceModel(
        id="workspace-api-candidates",
        tenant_id=tenant.id,
        project_id=project.id,
        name="Workspace Candidates",
        created_by=user.id,
        metadata_json={},
    )
    membership = WorkspaceMemberModel(
        id="wm-api-candidates",
        workspace_id=workspace.id,
        user_id=user.id,
        role="owner",
        invited_by=user.id,
    )
    root_task = WorkspaceTaskModel(
        id="task-api-candidates",
        workspace_id=workspace.id,
        title="Existing goal",
        created_by=user.id,
        status="todo",
        metadata_json={"task_role": "goal_root", "goal_origin": "human_defined"},
    )
    objective = CyberObjectiveModel(
        id="obj-api-candidates",
        workspace_id=workspace.id,
        title="Improve resilience",
        description="Objective description",
        obj_type="objective",
        progress=0.2,
        created_by=user.id,
    )
    post = BlackboardPostModel(
        id="post-api-candidates",
        workspace_id=workspace.id,
        author_id=user.id,
        title="Directive",
        content="Please prepare rollback checklist",
        status="open",
        is_pinned=True,
    )
    message = WorkspaceMessageModel(
        id="msg-api-candidates",
        workspace_id=workspace.id,
        sender_id=user.id,
        sender_type="human",
        content="Please prepare rollback checklist",
        mentions_json=[],
        metadata_json={},
    )
    user_tenant = UserTenant(
        id="ut-api-candidates",
        user_id=user.id,
        tenant_id=tenant.id,
        role="owner",
        permissions={"admin": True, "read": True, "write": True},
    )
    user_project = UserProject(
        id="up-api-candidates",
        user_id=user.id,
        project_id=project.id,
        role="owner",
    )

    test_db.add_all(
        [
            user,
            tenant,
            project,
            workspace,
            membership,
            root_task,
            objective,
            post,
            message,
            user_tenant,
            user_project,
        ]
    )
    await test_db.commit()

    response = await client.get(f"/api/v1/workspaces/{workspace.id}/goal-candidates")

    assert response.status_code == status.HTTP_200_OK
    payload = response.json()
    decisions = {item["candidate_text"]: item["decision"] for item in payload}
    assert decisions["Existing goal"] == "adopt_existing_goal"
    assert decisions["Improve resilience"] == "adopt_existing_goal"
    assert decisions["Please prepare rollback checklist"] == "formalize_new_goal"


@pytest.mark.asyncio
async def test_materialize_workspace_goal_candidate(authenticated_async_client, test_db) -> None:
    client: AsyncClient = authenticated_async_client

    user = User(
        id="550e8400-e29b-41d4-a716-446655440000",
        email="ws-api-materialize@example.com",
        hashed_password="hash",
        full_name="Owner",
        is_active=True,
    )
    tenant = Tenant(
        id="tenant-ws-api-materialize",
        name="TenantMaterialize",
        slug="tenant-ws-api-materialize",
        description="tenant",
        owner_id=user.id,
        plan="free",
        max_projects=10,
        max_users=10,
        max_storage=1024,
    )
    project = Project(
        id="project-ws-api-materialize",
        tenant_id=tenant.id,
        name="ProjectMaterialize",
        description="project",
        owner_id=user.id,
        memory_rules={},
        graph_config={},
    )
    workspace = WorkspaceModel(
        id="workspace-api-materialize",
        tenant_id=tenant.id,
        project_id=project.id,
        name="Workspace Materialize",
        created_by=user.id,
        metadata_json={},
    )
    membership = WorkspaceMemberModel(
        id="wm-api-materialize",
        workspace_id=workspace.id,
        user_id=user.id,
        role="owner",
        invited_by=user.id,
    )
    user_tenant = UserTenant(
        id="ut-api-materialize",
        user_id=user.id,
        tenant_id=tenant.id,
        role="owner",
        permissions={"admin": True, "read": True, "write": True},
    )
    user_project = UserProject(
        id="up-api-materialize",
        user_id=user.id,
        project_id=project.id,
        role="owner",
    )

    test_db.add_all(
        [user, tenant, project, workspace, membership, user_tenant, user_project]
    )
    await test_db.commit()

    response = await client.post(
        f"/api/v1/workspaces/{workspace.id}/goal-candidates/materialize",
        json={
            "candidate_id": "cand-1",
            "candidate_text": "Prepare rollback checklist",
            "candidate_kind": "inferred",
            "source_refs": ["message:msg-1"],
            "evidence_strength": 0.85,
            "source_breakdown": [
                {"source_type": "message_signal", "score": 0.85, "ref": "message:msg-1"}
            ],
            "freshness": 1.0,
            "urgency": 0.8,
            "user_intent_confidence": 0.85,
            "formalizable": True,
            "decision": "formalize_new_goal",
        },
    )

    assert response.status_code == status.HTTP_201_CREATED
    payload = response.json()
    assert payload["title"] == "Prepare rollback checklist"
    assert payload["metadata"]["task_role"] == "goal_root"
    assert payload["metadata"]["goal_origin"] == "agent_inferred"


@pytest.mark.asyncio
async def test_execution_task_mutations_reconcile_root_goal_progress(
    authenticated_async_client, test_db
) -> None:
    client: AsyncClient = authenticated_async_client

    user = User(
        id="550e8400-e29b-41d4-a716-446655440000",
        email="ws-api-root-progress@example.com",
        hashed_password="hash",
        full_name="Owner",
        is_active=True,
    )
    tenant = Tenant(
        id="tenant-ws-api-root-progress",
        name="TenantRootProgress",
        slug="tenant-ws-api-root-progress",
        description="tenant",
        owner_id=user.id,
        plan="free",
        max_projects=10,
        max_users=10,
        max_storage=1024,
    )
    project = Project(
        id="project-ws-api-root-progress",
        tenant_id=tenant.id,
        name="ProjectRootProgress",
        description="project",
        owner_id=user.id,
        memory_rules={},
        graph_config={},
    )
    workspace = WorkspaceModel(
        id="workspace-api-root-progress",
        tenant_id=tenant.id,
        project_id=project.id,
        name="Workspace Root Progress",
        created_by=user.id,
        metadata_json={},
    )
    membership = WorkspaceMemberModel(
        id="wm-api-root-progress",
        workspace_id=workspace.id,
        user_id=user.id,
        role="owner",
        invited_by=user.id,
    )
    root_task = WorkspaceTaskModel(
        id="root-api-progress",
        workspace_id=workspace.id,
        title="Root goal",
        created_by=user.id,
        status="todo",
        metadata_json={
            "autonomy_schema_version": 1,
            "task_role": "goal_root",
            "goal_origin": "human_defined",
            "goal_source_refs": ["task:root-api-progress"],
            "root_goal_policy": {
                "mutable_by_agent": False,
                "completion_requires_external_proof": True,
            },
        },
    )
    user_tenant = UserTenant(
        id="ut-api-root-progress",
        user_id=user.id,
        tenant_id=tenant.id,
        role="owner",
        permissions={"admin": True, "read": True, "write": True},
    )
    user_project = UserProject(
        id="up-api-root-progress",
        user_id=user.id,
        project_id=project.id,
        role="owner",
    )
    test_db.add_all(
        [user, tenant, project, workspace, membership, root_task, user_tenant, user_project]
    )
    await test_db.commit()

    create_response = await client.post(
        f"/api/v1/workspaces/{workspace.id}/tasks",
        json={
            "title": "Execution child",
            "metadata": {
                "autonomy_schema_version": 1,
                "task_role": "execution_task",
                "root_goal_task_id": root_task.id,
                "lineage_source": "agent",
            },
        },
    )

    assert create_response.status_code == status.HTTP_201_CREATED
    child_id = create_response.json()["id"]

    refreshed_root = await test_db.get(WorkspaceTaskModel, root_task.id)
    assert refreshed_root is not None
    await test_db.refresh(refreshed_root)
    assert refreshed_root.metadata_json["goal_health"] == "healthy"
    assert refreshed_root.metadata_json["active_child_task_ids"] == [child_id]
    assert refreshed_root.metadata_json["remediation_status"] == "none"

    start_response = await client.post(f"/api/v1/workspaces/{workspace.id}/tasks/{child_id}/start")
    assert start_response.status_code == status.HTTP_200_OK

    await test_db.refresh(refreshed_root)
    assert "1 in progress" in refreshed_root.metadata_json["goal_progress_summary"]
    assert refreshed_root.metadata_json["remediation_status"] == "none"

    block_response = await client.post(f"/api/v1/workspaces/{workspace.id}/tasks/{child_id}/block")
    assert block_response.status_code == status.HTTP_200_OK

    await test_db.refresh(refreshed_root)
    assert refreshed_root.metadata_json["goal_health"] == "blocked"
    assert refreshed_root.metadata_json["blocked_reason"] == "Execution child"
    assert refreshed_root.metadata_json["blocked_child_task_ids"] == [child_id]
    assert refreshed_root.metadata_json["remediation_status"] == "replan_required"
    assert "requires replan" in refreshed_root.metadata_json["remediation_summary"]

    complete_response = await client.post(
        f"/api/v1/workspaces/{workspace.id}/tasks/{child_id}/complete"
    )
    assert complete_response.status_code == status.HTTP_200_OK

    await test_db.refresh(refreshed_root)
    assert refreshed_root.metadata_json["goal_health"] == "achieved"
    assert refreshed_root.metadata_json["active_child_task_ids"] == []
    assert refreshed_root.metadata_json["blocked_child_task_ids"] == []
    assert refreshed_root.metadata_json["remediation_status"] == "ready_for_completion"
    assert "validate completion evidence" in refreshed_root.metadata_json["remediation_summary"]
