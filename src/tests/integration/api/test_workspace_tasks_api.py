"""Integration tests for workspace task delegation API."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import status
from httpx import AsyncClient
from sqlalchemy import select

from src.application.services.workspace_mention_router import WorkspaceMentionRouter
from src.application.services.workspace_task_event_publisher import (
    WorkspaceTaskEventPublisher,
)
from src.domain.model.workspace.workspace_task import WorkspaceTaskStatus
from src.infrastructure.adapters.secondary.persistence.models import (
    AgentDefinitionModel,
    BlackboardPostModel,
    Conversation as ConversationModel,
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
    WorkspaceTaskSessionAttemptModel,
)
from src.infrastructure.agent.sisyphus.builtin_agent import BUILTIN_SISYPHUS_ID
from src.infrastructure.agent.subagent.task_decomposer import DecompositionResult, SubTask
from src.infrastructure.agent.workspace.workspace_goal_runtime import (
    _launch_workspace_retry_attempt,
    adjudicate_workspace_worker_report,
    apply_workspace_worker_report,
    maybe_materialize_workspace_goal_candidate,
    should_activate_workspace_authority,
)


@pytest.mark.asyncio
async def test_assign_agent_rejects_cross_workspace_binding(
    authenticated_async_client, test_db
) -> None:
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
async def test_state_transition_validation_for_complete(
    authenticated_async_client, test_db
) -> None:
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
        [
            user,
            tenant,
            project,
            workspace,
            membership,
            agent,
            binding,
            task,
            user_tenant,
            user_project,
        ]
    )
    await test_db.commit()

    response = await client.post(
        f"/api/v1/workspaces/{workspace.id}/tasks/{task.id}/assign-agent",
        json={"workspace_agent_id": binding.id},
    )

    assert response.status_code == status.HTTP_200_OK
    assigned_event = next(
        payload
        for event_type, payload in published_events
        if event_type == "workspace_task_assigned"
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
        (
            await test_db.execute(
                WorkspaceMessageModel.__table__.select().where(
                    WorkspaceMessageModel.workspace_id == workspace.id
                )
            )
        )
        .mappings()
        .first()
    )
    assert message is not None
    assert '@"Leader Agent"' in message["content"]
    assert "objective" in message["content"].lower()
    assert "workspace task" in message["content"].lower()
    assert should_activate_workspace_authority(message["content"]) is True
    assert triggered["workspace_id"] == workspace.id
    triggered_message = triggered["message"]
    assert triggered_message.mentions == [agent.id]
    assert triggered_message.metadata["conversation_scope"] == f"objective:{response.json()['id']}"
    projected_root = (
        (
            await test_db.execute(
                select(WorkspaceTaskModel).where(
                    WorkspaceTaskModel.workspace_id == workspace.id,
                    WorkspaceTaskModel.metadata_json["objective_id"].as_string()
                    == response.json()["id"],
                )
            )
        )
        .scalars()
        .first()
    )
    assert projected_root is not None
    assert projected_root.metadata_json["task_role"] == "goal_root"
    assert projected_root.metadata_json["goal_origin"] == "existing_objective"


@pytest.mark.asyncio
async def test_create_objective_force_injects_leader_mention_for_routing(
    authenticated_async_client, test_db, monkeypatch
) -> None:
    from src.domain.model.workspace.workspace_message import MessageSenderType, WorkspaceMessage

    client: AsyncClient = authenticated_async_client
    triggered: dict[str, object] = {}

    def _capture_fire(**kwargs: object) -> None:
        triggered.update(kwargs)

    class _FakeMessageService:
        async def send_message(self, **kwargs: object) -> WorkspaceMessage:
            return WorkspaceMessage(
                workspace_id=str(kwargs["workspace_id"]),
                sender_id=str(kwargs["sender_id"]),
                sender_type=MessageSenderType.HUMAN,
                content=str(kwargs["content"]),
                mentions=[],
                metadata={"sender_name": str(kwargs["sender_name"])},
            )

    monkeypatch.setattr(
        "src.infrastructure.adapters.primary.web.routers.cyber_objectives._fire_mention_routing",
        _capture_fire,
    )
    monkeypatch.setattr(
        "src.infrastructure.adapters.primary.web.routers.cyber_objectives.get_message_service",
        lambda request, db: _FakeMessageService(),
    )

    user = User(
        id="550e8400-e29b-41d4-a716-446655440000",
        email="ws-api-objective-force-mention@example.com",
        hashed_password="hash",
        full_name="Owner",
        is_active=True,
    )
    tenant = Tenant(
        id="tenant-ws-api-objective-force-mention",
        name="TenantObjectiveForceMention",
        slug="tenant-ws-api-objective-force-mention",
        description="tenant",
        owner_id=user.id,
        plan="free",
        max_projects=10,
        max_users=10,
        max_storage=1024,
    )
    project = Project(
        id="project-ws-api-objective-force-mention",
        tenant_id=tenant.id,
        name="ProjectObjectiveForceMention",
        description="project",
        owner_id=user.id,
        memory_rules={},
        graph_config={},
    )
    workspace = WorkspaceModel(
        id="workspace-api-objective-force-mention",
        tenant_id=tenant.id,
        project_id=project.id,
        name="Workspace Objective Force Mention",
        created_by=user.id,
        metadata_json={},
    )
    membership = WorkspaceMemberModel(
        id="wm-api-objective-force-mention",
        workspace_id=workspace.id,
        user_id=user.id,
        role="owner",
        invited_by=user.id,
    )
    agent = AgentDefinitionModel(
        id="agent-api-objective-force-mention",
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
        id="wa-api-objective-force-mention",
        workspace_id=workspace.id,
        agent_id=agent.id,
        display_name="Leader Agent",
        description=None,
        config_json={},
        is_active=True,
    )
    user_tenant = UserTenant(
        id="ut-api-objective-force-mention",
        user_id=user.id,
        tenant_id=tenant.id,
        role="owner",
        permissions={"admin": True, "read": True, "write": True},
    )
    user_project = UserProject(
        id="up-api-objective-force-mention",
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
        json={"title": "Ship fallback objective", "obj_type": "objective"},
    )

    assert response.status_code == status.HTTP_201_CREATED
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

    assert response.status_code == status.HTTP_403_FORBIDDEN
    assert "Sisyphus leader" in response.json()["detail"]


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
                "signals": [
                    {"source_type": "message_signal", "ref": "message:msg-1", "score": 0.85}
                ],
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

    assert response.status_code == status.HTTP_403_FORBIDDEN
    assert "Sisyphus leader" in response.json()["detail"]


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
                "signals": [
                    {"source_type": "message_signal", "ref": "message:msg-1", "score": 0.85}
                ],
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

    assert response.status_code == status.HTTP_403_FORBIDDEN
    assert "Sisyphus leader" in response.json()["detail"]


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
async def test_list_workspace_goal_candidates_self_heals_legacy_sisyphus_name_conflict(
    authenticated_async_client, test_db, monkeypatch
) -> None:
    client: AsyncClient = authenticated_async_client
    triggered: dict[str, object] = {}

    def _capture_fire(**kwargs: object) -> None:
        triggered.update(kwargs)

    monkeypatch.setattr(
        "src.infrastructure.adapters.primary.web.routers.workspace_leader_bootstrap._fire_mention_routing",
        _capture_fire,
    )

    user = User(
        id="550e8400-e29b-41d4-a716-446655440000",
        email="ws-api-candidates-conflict@example.com",
        hashed_password="hash",
        full_name="Owner",
        is_active=True,
    )
    tenant = Tenant(
        id="tenant-ws-api-candidates-conflict",
        name="TenantCandidatesConflict",
        slug="tenant-ws-api-candidates-conflict",
        description="tenant",
        owner_id=user.id,
        plan="free",
        max_projects=10,
        max_users=10,
        max_storage=1024,
    )
    project = Project(
        id="project-ws-api-candidates-conflict",
        tenant_id=tenant.id,
        name="ProjectCandidatesConflict",
        description="project",
        owner_id=user.id,
        memory_rules={},
        graph_config={},
    )
    workspace = WorkspaceModel(
        id="workspace-api-candidates-conflict",
        tenant_id=tenant.id,
        project_id=project.id,
        name="Workspace Candidates Conflict",
        created_by=user.id,
        metadata_json={},
    )
    membership = WorkspaceMemberModel(
        id="wm-api-candidates-conflict",
        workspace_id=workspace.id,
        user_id=user.id,
        role="owner",
        invited_by=user.id,
    )
    root_task = WorkspaceTaskModel(
        id="task-api-candidates-conflict",
        workspace_id=workspace.id,
        title="Existing goal",
        created_by=user.id,
        status="todo",
        metadata_json={"task_role": "goal_root", "goal_origin": "human_defined"},
    )
    objective = CyberObjectiveModel(
        id="obj-api-candidates-conflict",
        workspace_id=workspace.id,
        title="Improve resilience",
        description="Objective description",
        obj_type="objective",
        progress=0.2,
        created_by=user.id,
    )
    conflicting_agent = AgentDefinitionModel(
        id="legacy-sisyphus",
        tenant_id=tenant.id,
        project_id=project.id,
        name="sisyphus",
        display_name="Legacy Sisyphus",
        system_prompt="Legacy builtin row",
        allowed_tools=[],
        allowed_skills=[],
        allowed_mcp_servers=[],
        source="database",
    )
    user_tenant = UserTenant(
        id="ut-api-candidates-conflict",
        user_id=user.id,
        tenant_id=tenant.id,
        role="owner",
        permissions={"admin": True, "read": True, "write": True},
    )
    user_project = UserProject(
        id="up-api-candidates-conflict",
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
            conflicting_agent,
            user_tenant,
            user_project,
        ]
    )
    await test_db.commit()

    response = await client.get(f"/api/v1/workspaces/{workspace.id}/goal-candidates")

    assert response.status_code == status.HTTP_200_OK
    decisions = {item["candidate_text"]: item["decision"] for item in response.json()}
    assert decisions["Existing goal"] == "adopt_existing_goal"
    assert decisions["Improve resilience"] == "adopt_existing_goal"
    builtin_agent = await test_db.get(AgentDefinitionModel, BUILTIN_SISYPHUS_ID)
    assert builtin_agent is not None
    await test_db.refresh(conflicting_agent)
    legacy_agent = conflicting_agent
    assert legacy_agent.name == f"sisyphus-legacy-{conflicting_agent.id}"
    assert legacy_agent.metadata_json["renamed_from_builtin_name"] == "sisyphus"
    assert legacy_agent.metadata_json["renamed_for_builtin_id"] == BUILTIN_SISYPHUS_ID
    binding = await test_db.scalar(
        select(WorkspaceAgentModel).where(WorkspaceAgentModel.workspace_id == workspace.id)
    )
    assert binding is not None
    assert binding.agent_id == BUILTIN_SISYPHUS_ID
    message = await test_db.scalar(
        select(WorkspaceMessageModel).where(WorkspaceMessageModel.workspace_id == workspace.id)
    )
    assert message is not None
    assert message.mentions_json == [BUILTIN_SISYPHUS_ID]
    assert triggered["workspace_id"] == workspace.id
    assert triggered["message"].mentions == [BUILTIN_SISYPHUS_ID]


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

    test_db.add_all([user, tenant, project, workspace, membership, user_tenant, user_project])
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
    assert start_response.status_code == status.HTTP_403_FORBIDDEN
    assert "Root goal must leave todo" in start_response.json()["detail"]

    block_response = await client.post(f"/api/v1/workspaces/{workspace.id}/tasks/{child_id}/block")
    assert block_response.status_code == status.HTTP_403_FORBIDDEN
    assert "assigned worker authority" in block_response.json()["detail"]

    complete_response = await client.post(
        f"/api/v1/workspaces/{workspace.id}/tasks/{child_id}/complete"
    )
    assert complete_response.status_code == status.HTTP_403_FORBIDDEN
    assert "assigned worker authority" in complete_response.json()["detail"]

    await test_db.refresh(refreshed_root)
    assert refreshed_root.metadata_json["goal_health"] == "healthy"
    assert refreshed_root.metadata_json["active_child_task_ids"] == [child_id]
    assert refreshed_root.metadata_json["remediation_status"] == "none"


@pytest.mark.asyncio
async def test_blackboard_triggered_runtime_skips_inferred_root_creation_without_existing_root(
    test_db,
) -> None:
    user = User(
        id="550e8400-e29b-41d4-a716-446655440100",
        email="ws-api-runtime-start@example.com",
        hashed_password="hash",
        full_name="Owner",
        is_active=True,
    )
    tenant = Tenant(
        id="tenant-ws-runtime-start",
        name="TenantRuntimeStart",
        slug="tenant-ws-runtime-start",
        description="tenant",
        owner_id=user.id,
        plan="free",
        max_projects=10,
        max_users=10,
        max_storage=1024,
    )
    project = Project(
        id="project-ws-runtime-start",
        tenant_id=tenant.id,
        name="ProjectRuntimeStart",
        description="project",
        owner_id=user.id,
        memory_rules={},
        graph_config={},
    )
    workspace = WorkspaceModel(
        id="workspace-runtime-start",
        tenant_id=tenant.id,
        project_id=project.id,
        name="Workspace Runtime Start",
        created_by=user.id,
        metadata_json={},
    )
    membership = WorkspaceMemberModel(
        id="wm-runtime-start",
        workspace_id=workspace.id,
        user_id=user.id,
        role="owner",
        invited_by=user.id,
    )
    blackboard_post = BlackboardPostModel(
        id="post-runtime-start",
        workspace_id=workspace.id,
        author_id=user.id,
        title="Directive",
        content="Please prepare rollback checklist",
        status="open",
        is_pinned=True,
    )
    user_tenant = UserTenant(
        id="ut-runtime-start",
        user_id=user.id,
        tenant_id=tenant.id,
        role="owner",
        permissions={"admin": True, "read": True, "write": True},
    )
    user_project = UserProject(
        id="up-runtime-start",
        user_id=user.id,
        project_id=project.id,
        role="owner",
    )
    test_db.add_all(
        [user, tenant, project, workspace, membership, blackboard_post, user_tenant, user_project]
    )
    await test_db.commit()

    task_decomposer = AsyncMock()
    task_decomposer.decompose.return_value = DecompositionResult(
        subtasks=(SubTask(id="t1", description="Draft checklist"),),
        is_decomposed=True,
    )

    @asynccontextmanager
    async def fake_session_factory():
        yield test_db

    with (
        patch(
            "src.infrastructure.agent.workspace.workspace_goal_runtime.async_session_factory",
            fake_session_factory,
        ),
        patch(
            "src.infrastructure.agent.workspace.workspace_goal_runtime.get_redis_client",
            AsyncMock(return_value=None),
        ),
    ):
        root_task = await maybe_materialize_workspace_goal_candidate(
            project.id,
            tenant.id,
            user.id,
            task_decomposer=task_decomposer,
            user_query="Please prepare rollback checklist",
        )

    assert root_task is None
    persisted_tasks = (
        (
            await test_db.execute(
                select(WorkspaceTaskModel).where(WorkspaceTaskModel.workspace_id == workspace.id)
            )
        )
        .scalars()
        .all()
    )
    assert persisted_tasks == []


@pytest.mark.asyncio
async def test_blackboard_triggered_runtime_completes_root_on_ready_for_completion(test_db) -> None:
    user = User(
        id="550e8400-e29b-41d4-a716-446655440101",
        email="ws-api-runtime-complete@example.com",
        hashed_password="hash",
        full_name="Owner",
        is_active=True,
    )
    tenant = Tenant(
        id="tenant-ws-runtime-complete",
        name="TenantRuntimeComplete",
        slug="tenant-ws-runtime-complete",
        description="tenant",
        owner_id=user.id,
        plan="free",
        max_projects=10,
        max_users=10,
        max_storage=1024,
    )
    project = Project(
        id="project-ws-runtime-complete",
        tenant_id=tenant.id,
        name="ProjectRuntimeComplete",
        description="project",
        owner_id=user.id,
        memory_rules={},
        graph_config={},
    )
    workspace = WorkspaceModel(
        id="workspace-runtime-complete",
        tenant_id=tenant.id,
        project_id=project.id,
        name="Workspace Runtime Complete",
        created_by=user.id,
        metadata_json={},
    )
    membership = WorkspaceMemberModel(
        id="wm-runtime-complete",
        workspace_id=workspace.id,
        user_id=user.id,
        role="owner",
        invited_by=user.id,
    )
    root_task = WorkspaceTaskModel(
        id="root-runtime-complete",
        workspace_id=workspace.id,
        title="Prepare rollback checklist",
        created_by=user.id,
        status="in_progress",
        metadata_json={
            "autonomy_schema_version": 1,
            "task_role": "goal_root",
            "goal_origin": "agent_inferred",
            "goal_source_refs": ["blackboard:post-runtime-complete"],
            "goal_evidence_bundle": {
                "score": 0.85,
                "signals": [
                    {
                        "source_type": "blackboard_signal",
                        "ref": "blackboard:post-runtime-complete",
                        "score": 0.85,
                    }
                ],
                "formalized_at": "2026-04-16T03:00:00Z",
            },
            "remediation_status": "ready_for_completion",
        },
    )
    child_task = WorkspaceTaskModel(
        id="child-runtime-complete",
        workspace_id=workspace.id,
        title="Draft checklist",
        created_by=user.id,
        status="done",
        completed_at=datetime.now(UTC),
        metadata_json={
            "autonomy_schema_version": 1,
            "task_role": "execution_task",
            "root_goal_task_id": root_task.id,
            "lineage_source": "agent",
            "evidence_refs": ["artifact:file-1"],
            "execution_verifications": ["browser_assert:rollback_check"],
        },
    )
    blackboard_post = BlackboardPostModel(
        id="post-runtime-complete",
        workspace_id=workspace.id,
        author_id=user.id,
        title="Directive",
        content="Please prepare rollback checklist",
        status="open",
        is_pinned=True,
    )
    user_tenant = UserTenant(
        id="ut-runtime-complete",
        user_id=user.id,
        tenant_id=tenant.id,
        role="owner",
        permissions={"admin": True, "read": True, "write": True},
    )
    user_project = UserProject(
        id="up-runtime-complete",
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
            child_task,
            blackboard_post,
            user_tenant,
            user_project,
        ]
    )
    await test_db.commit()

    @asynccontextmanager
    async def fake_session_factory():
        yield test_db

    with (
        patch(
            "src.infrastructure.agent.workspace.workspace_goal_runtime.async_session_factory",
            fake_session_factory,
        ),
        patch(
            "src.infrastructure.agent.workspace.workspace_goal_runtime.get_redis_client",
            AsyncMock(return_value=None),
        ),
    ):
        result = await maybe_materialize_workspace_goal_candidate(
            project.id,
            tenant.id,
            user.id,
            user_query="Please prepare rollback checklist",
        )

    assert result is not None
    refreshed_root = await test_db.get(WorkspaceTaskModel, root_task.id)
    assert refreshed_root is not None
    await test_db.refresh(refreshed_root)
    assert refreshed_root.status == "done"
    assert "goal_evidence" in refreshed_root.metadata_json
    assert refreshed_root.metadata_json["goal_evidence"]["verification_grade"] in {"pass", "warn"}


@pytest.mark.asyncio
async def test_blackboard_triggered_runtime_blocks_root_only_for_human_review_escalation(
    test_db,
) -> None:
    user = User(
        id="550e8400-e29b-41d4-a716-446655440102",
        email="ws-api-runtime-block@example.com",
        hashed_password="hash",
        full_name="Owner",
        is_active=True,
    )
    tenant = Tenant(
        id="tenant-ws-runtime-block",
        name="TenantRuntimeBlock",
        slug="tenant-ws-runtime-block",
        description="tenant",
        owner_id=user.id,
        plan="free",
        max_projects=10,
        max_users=10,
        max_storage=1024,
    )
    project = Project(
        id="project-ws-runtime-block",
        tenant_id=tenant.id,
        name="ProjectRuntimeBlock",
        description="project",
        owner_id=user.id,
        memory_rules={},
        graph_config={},
    )
    workspace = WorkspaceModel(
        id="workspace-runtime-block",
        tenant_id=tenant.id,
        project_id=project.id,
        name="Workspace Runtime Block",
        created_by=user.id,
        metadata_json={},
    )
    membership = WorkspaceMemberModel(
        id="wm-runtime-block",
        workspace_id=workspace.id,
        user_id=user.id,
        role="owner",
        invited_by=user.id,
    )
    root_task = WorkspaceTaskModel(
        id="root-runtime-block",
        workspace_id=workspace.id,
        title="Prepare rollback checklist",
        created_by=user.id,
        status="in_progress",
        metadata_json={
            "autonomy_schema_version": 1,
            "task_role": "goal_root",
            "goal_origin": "agent_inferred",
            "goal_source_refs": ["blackboard:post-runtime-block"],
            "goal_evidence_bundle": {
                "score": 0.85,
                "signals": [
                    {
                        "source_type": "blackboard_signal",
                        "ref": "blackboard:post-runtime-block",
                        "score": 0.85,
                    }
                ],
                "formalized_at": "2026-04-16T03:00:00Z",
            },
            "remediation_status": "replan_required",
            "replan_attempt_count": 2,
        },
    )
    blackboard_post = BlackboardPostModel(
        id="post-runtime-block",
        workspace_id=workspace.id,
        author_id=user.id,
        title="Directive",
        content="Please prepare rollback checklist",
        status="open",
        is_pinned=True,
    )
    user_tenant = UserTenant(
        id="ut-runtime-block",
        user_id=user.id,
        tenant_id=tenant.id,
        role="owner",
        permissions={"admin": True, "read": True, "write": True},
    )
    user_project = UserProject(
        id="up-runtime-block",
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
            blackboard_post,
            user_tenant,
            user_project,
        ]
    )
    await test_db.commit()

    @asynccontextmanager
    async def fake_session_factory():
        yield test_db

    with (
        patch(
            "src.infrastructure.agent.workspace.workspace_goal_runtime.async_session_factory",
            fake_session_factory,
        ),
        patch(
            "src.infrastructure.agent.workspace.workspace_goal_runtime.get_redis_client",
            AsyncMock(return_value=None),
        ),
    ):
        result = await maybe_materialize_workspace_goal_candidate(
            project.id,
            tenant.id,
            user.id,
            user_query="Please prepare rollback checklist",
        )

    assert result is not None
    refreshed_root = await test_db.get(WorkspaceTaskModel, root_task.id)
    assert refreshed_root is not None
    await test_db.refresh(refreshed_root)
    assert refreshed_root.status == "blocked"
    assert "requires human review" in refreshed_root.metadata_json["remediation_summary"]


@pytest.mark.asyncio
async def test_retry_launch_creates_scoped_conversation_and_streams_agent_execution(test_db) -> None:
    user = User(
        id="550e8400-e29b-41d4-a716-446655440103",
        email="ws-api-retry-launch@example.com",
        hashed_password="hash",
        full_name="Owner",
        is_active=True,
    )
    tenant = Tenant(
        id="tenant-ws-retry-launch",
        name="TenantRetryLaunch",
        slug="tenant-ws-retry-launch",
        description="tenant",
        owner_id=user.id,
        plan="free",
        max_projects=10,
        max_users=10,
        max_storage=1024,
    )
    project = Project(
        id="project-ws-retry-launch",
        tenant_id=tenant.id,
        name="ProjectRetryLaunch",
        description="project",
        owner_id=user.id,
        memory_rules={},
        graph_config={},
    )
    workspace = WorkspaceModel(
        id="workspace-retry-launch",
        tenant_id=tenant.id,
        project_id=project.id,
        name="Workspace Retry Launch",
        created_by=user.id,
        metadata_json={},
    )
    membership = WorkspaceMemberModel(
        id="wm-retry-launch",
        workspace_id=workspace.id,
        user_id=user.id,
        role="owner",
        invited_by=user.id,
    )
    test_db.add_all([user, tenant, project, workspace, membership])
    await test_db.commit()

    @asynccontextmanager
    async def fake_session_factory():
        yield test_db

    captured: dict[str, object] = {}

    async def _stream_chat_v2(**kwargs: object):
        captured.update(kwargs)
        yield {"type": "complete", "data": {"content": "retry launched"}}

    agent_service = MagicMock()
    agent_service.stream_chat_v2 = _stream_chat_v2

    with (
        patch(
            "src.infrastructure.agent.workspace.workspace_goal_runtime.async_session_factory",
            fake_session_factory,
        ),
        patch(
            "src.infrastructure.agent.workspace.workspace_goal_runtime.get_redis_client",
            AsyncMock(return_value=None),
        ),
        patch(
            "src.configuration.factories.create_llm_client",
            new=AsyncMock(return_value=object()),
        ),
        patch(
            "src.configuration.di_container.DIContainer.agent_service",
            return_value=agent_service,
        ),
    ):
        await _launch_workspace_retry_attempt(
            workspace_id=workspace.id,
            root_goal_task_id="root-retry-launch",
            workspace_task_id="child-retry-launch",
            attempt_id="attempt-retry-launch-1",
            actor_user_id=user.id,
            leader_agent_id="leader-agent",
            retry_feedback="Please tighten verification",
        )

    expected_conversation_id = WorkspaceMentionRouter.workspace_conversation_id(
        workspace.id,
        "leader-agent",
        conversation_scope="task:child-retry-launch:attempt:attempt-retry-launch-1",
    )
    conversation = await test_db.scalar(
        select(ConversationModel).where(ConversationModel.id == expected_conversation_id)
    )
    assert conversation is not None
    assert conversation.meta["workspace_task_id"] == "child-retry-launch"
    assert conversation.meta["attempt_id"] == "attempt-retry-launch-1"
    assert conversation.meta["retry_launch"] is True
    assert captured["conversation_id"] == expected_conversation_id
    assert captured["project_id"] == project.id
    assert captured["tenant_id"] == tenant.id
    assert captured["agent_id"] == "leader-agent"
    assert "attempt_id=attempt-retry-launch-1" in str(captured["user_message"])
    assert "Leader retry feedback: Please tighten verification" in str(captured["user_message"])


@pytest.mark.asyncio
async def test_leader_reject_creates_retry_attempt_and_followup_conversation(test_db) -> None:
    user = User(
        id="550e8400-e29b-41d4-a716-446655440104",
        email="ws-api-retry-scenario@example.com",
        hashed_password="hash",
        full_name="Owner",
        is_active=True,
    )
    tenant = Tenant(
        id="tenant-ws-retry-scenario",
        name="TenantRetryScenario",
        slug="tenant-ws-retry-scenario",
        description="tenant",
        owner_id=user.id,
        plan="free",
        max_projects=10,
        max_users=10,
        max_storage=1024,
    )
    project = Project(
        id="project-ws-retry-scenario",
        tenant_id=tenant.id,
        name="ProjectRetryScenario",
        description="project",
        owner_id=user.id,
        memory_rules={},
        graph_config={},
    )
    workspace = WorkspaceModel(
        id="workspace-retry-scenario",
        tenant_id=tenant.id,
        project_id=project.id,
        name="Workspace Retry Scenario",
        created_by=user.id,
        metadata_json={},
    )
    membership = WorkspaceMemberModel(
        id="wm-retry-scenario",
        workspace_id=workspace.id,
        user_id=user.id,
        role="owner",
        invited_by=user.id,
    )
    root_task = WorkspaceTaskModel(
        id="root-retry-scenario",
        workspace_id=workspace.id,
        title="Prepare rollback checklist",
        created_by=user.id,
        status="in_progress",
        metadata_json={
            "autonomy_schema_version": 1,
            "task_role": "goal_root",
            "goal_origin": "human_defined",
            "goal_source_refs": ["objective:obj-retry-scenario"],
        },
    )
    child_task = WorkspaceTaskModel(
        id="child-retry-scenario",
        workspace_id=workspace.id,
        title="Draft checklist",
        created_by=user.id,
        assignee_agent_id="worker-agent",
        status="in_progress",
        metadata_json={
            "autonomy_schema_version": 1,
            "task_role": "execution_task",
            "root_goal_task_id": root_task.id,
            "lineage_source": "agent",
            "pending_leader_adjudication": True,
            "current_attempt_id": "attempt-retry-scenario-1",
            "last_attempt_id": "attempt-retry-scenario-1",
            "current_attempt_number": 1,
            "last_attempt_status": "awaiting_leader_adjudication",
            "last_worker_report_summary": "Need stronger verification",
        },
    )
    attempt = WorkspaceTaskSessionAttemptModel(
        id="attempt-retry-scenario-1",
        workspace_task_id=child_task.id,
        root_goal_task_id=root_task.id,
        workspace_id=workspace.id,
        attempt_number=1,
        status="awaiting_leader_adjudication",
        worker_agent_id="worker-agent",
        leader_agent_id="leader-agent",
        candidate_summary="Need stronger verification",
        candidate_artifacts_json=[],
        candidate_verifications_json=["worker_report:completed"],
    )
    user_tenant = UserTenant(
        id="ut-retry-scenario",
        user_id=user.id,
        tenant_id=tenant.id,
        role="owner",
        permissions={"admin": True, "read": True, "write": True},
    )
    user_project = UserProject(
        id="up-retry-scenario",
        user_id=user.id,
        project_id=project.id,
        role="owner",
    )
    test_db.add_all([
        user, tenant, project, workspace, membership, root_task, child_task, attempt, user_tenant, user_project
    ])
    await test_db.commit()

    @asynccontextmanager
    async def fake_session_factory():
        yield test_db

    captured: dict[str, object] = {}
    scheduled: list[dict[str, str]] = []

    async def _stream_chat_v2(**kwargs: object):
        captured.update(kwargs)
        yield {"type": "complete", "data": {"content": "retry launched"}}

    agent_service = MagicMock()
    agent_service.stream_chat_v2 = _stream_chat_v2

    with (
        patch(
            "src.infrastructure.agent.workspace.workspace_goal_runtime.async_session_factory",
            fake_session_factory,
        ),
        patch(
            "src.infrastructure.agent.workspace.workspace_goal_runtime.get_redis_client",
            AsyncMock(return_value=None),
        ),
        patch(
            "src.configuration.factories.create_llm_client",
            new=AsyncMock(return_value=object()),
        ),
        patch(
            "src.configuration.di_container.DIContainer.agent_service",
            return_value=agent_service,
        ),
        patch(
            "src.infrastructure.agent.workspace.workspace_goal_runtime._schedule_workspace_retry_attempt",
            side_effect=lambda **kwargs: scheduled.append(kwargs),
        ),
    ):
        result = await adjudicate_workspace_worker_report(
            workspace_id=workspace.id,
            task_id=child_task.id,
            actor_user_id=user.id,
            status=WorkspaceTaskStatus.IN_PROGRESS,
            leader_agent_id="leader-agent",
        )

        assert result is not None
        attempts = (
            await test_db.execute(
                select(WorkspaceTaskSessionAttemptModel)
                .where(WorkspaceTaskSessionAttemptModel.workspace_task_id == child_task.id)
                .order_by(WorkspaceTaskSessionAttemptModel.attempt_number.asc())
            )
        ).scalars().all()
        assert len(attempts) == 2
        assert attempts[0].status == "rejected"
        assert attempts[1].status == "pending"
        assert len(scheduled) == 1
        assert scheduled[0]["attempt_id"] == attempts[1].id

        await _launch_workspace_retry_attempt(**scheduled[0])

    expected_conversation_id = WorkspaceMentionRouter.workspace_conversation_id(
        workspace.id,
        "leader-agent",
        conversation_scope=f"task:{child_task.id}:attempt:{attempts[1].id}",
    )
    conversation = await test_db.scalar(
        select(ConversationModel).where(ConversationModel.id == expected_conversation_id)
    )
    assert conversation is not None
    assert conversation.meta["workspace_task_id"] == child_task.id
    assert conversation.meta["attempt_id"] == attempts[1].id
    assert conversation.meta["retry_launch"] is True
    await test_db.refresh(child_task)
    assert child_task.metadata_json["current_attempt_id"] == attempts[1].id
    assert child_task.metadata_json["current_attempt_number"] == 2
    assert child_task.metadata_json["last_attempt_status"] == "rejected"
    assert captured["conversation_id"] == expected_conversation_id
    assert captured["agent_id"] == "leader-agent"
    assert "attempt_id=" + attempts[1].id in str(captured["user_message"])


@pytest.mark.asyncio
async def test_retry_followup_launch_can_ingest_new_candidate_and_return_to_adjudication(test_db) -> None:
    user = User(
        id="550e8400-e29b-41d4-a716-446655440105",
        email="ws-api-retry-followup@example.com",
        hashed_password="hash",
        full_name="Owner",
        is_active=True,
    )
    tenant = Tenant(
        id="tenant-ws-retry-followup",
        name="TenantRetryFollowup",
        slug="tenant-ws-retry-followup",
        description="tenant",
        owner_id=user.id,
        plan="free",
        max_projects=10,
        max_users=10,
        max_storage=1024,
    )
    project = Project(
        id="project-ws-retry-followup",
        tenant_id=tenant.id,
        name="ProjectRetryFollowup",
        description="project",
        owner_id=user.id,
        memory_rules={},
        graph_config={},
    )
    workspace = WorkspaceModel(
        id="workspace-retry-followup",
        tenant_id=tenant.id,
        project_id=project.id,
        name="Workspace Retry Followup",
        created_by=user.id,
        metadata_json={},
    )
    membership = WorkspaceMemberModel(
        id="wm-retry-followup",
        workspace_id=workspace.id,
        user_id=user.id,
        role="owner",
        invited_by=user.id,
    )
    root_task = WorkspaceTaskModel(
        id="root-retry-followup",
        workspace_id=workspace.id,
        title="Prepare rollback checklist",
        created_by=user.id,
        status="in_progress",
        metadata_json={
            "autonomy_schema_version": 1,
            "task_role": "goal_root",
            "goal_origin": "human_defined",
            "goal_source_refs": ["objective:obj-retry-followup"],
        },
    )
    child_task = WorkspaceTaskModel(
        id="child-retry-followup",
        workspace_id=workspace.id,
        title="Draft checklist",
        created_by=user.id,
        assignee_agent_id="worker-agent",
        status="in_progress",
        metadata_json={
            "autonomy_schema_version": 1,
            "task_role": "execution_task",
            "root_goal_task_id": root_task.id,
            "lineage_source": "agent",
            "pending_leader_adjudication": True,
            "current_attempt_id": "attempt-retry-followup-1",
            "last_attempt_id": "attempt-retry-followup-1",
            "current_attempt_number": 1,
            "last_attempt_status": "awaiting_leader_adjudication",
            "last_worker_report_summary": "Need stronger verification",
        },
    )
    attempt = WorkspaceTaskSessionAttemptModel(
        id="attempt-retry-followup-1",
        workspace_task_id=child_task.id,
        root_goal_task_id=root_task.id,
        workspace_id=workspace.id,
        attempt_number=1,
        status="awaiting_leader_adjudication",
        worker_agent_id="worker-agent",
        leader_agent_id="leader-agent",
        candidate_summary="Need stronger verification",
        candidate_artifacts_json=[],
        candidate_verifications_json=["worker_report:completed"],
    )
    user_tenant = UserTenant(
        id="ut-retry-followup",
        user_id=user.id,
        tenant_id=tenant.id,
        role="owner",
        permissions={"admin": True, "read": True, "write": True},
    )
    user_project = UserProject(
        id="up-retry-followup",
        user_id=user.id,
        project_id=project.id,
        role="owner",
    )
    test_db.add_all(
        [user, tenant, project, workspace, membership, root_task, child_task, attempt, user_tenant, user_project]
    )
    await test_db.commit()

    @asynccontextmanager
    async def fake_session_factory():
        yield test_db

    scheduled: list[dict[str, str]] = []
    captured: dict[str, object] = {}

    async def _stream_chat_v2(**kwargs: object):
        captured.update(kwargs)
        await apply_workspace_worker_report(
            workspace_id=workspace.id,
            root_goal_task_id=root_task.id,
            task_id=child_task.id,
            attempt_id=str(kwargs["user_message"]).split("attempt_id=")[1].splitlines()[0],
            conversation_id=str(kwargs["conversation_id"]),
            actor_user_id=user.id,
            worker_agent_id="worker-agent",
            report_type="completed",
            summary="Retry candidate completed",
            artifacts=["artifact:retry-followup"],
            leader_agent_id="leader-agent",
            report_id="retry-followup-run-1",
        )
        yield {"type": "complete", "data": {"content": "retry loop complete"}}

    agent_service = MagicMock()
    agent_service.stream_chat_v2 = _stream_chat_v2

    with (
        patch(
            "src.infrastructure.agent.workspace.workspace_goal_runtime.async_session_factory",
            fake_session_factory,
        ),
        patch(
            "src.infrastructure.agent.workspace.workspace_goal_runtime.get_redis_client",
            AsyncMock(return_value=None),
        ),
        patch(
            "src.configuration.factories.create_llm_client",
            new=AsyncMock(return_value=object()),
        ),
        patch(
            "src.configuration.di_container.DIContainer.agent_service",
            return_value=agent_service,
        ),
        patch(
            "src.infrastructure.agent.workspace.workspace_goal_runtime._schedule_workspace_retry_attempt",
            side_effect=lambda **kwargs: scheduled.append(kwargs),
        ),
    ):
        rejected = await adjudicate_workspace_worker_report(
            workspace_id=workspace.id,
            task_id=child_task.id,
            actor_user_id=user.id,
            status=WorkspaceTaskStatus.IN_PROGRESS,
            leader_agent_id="leader-agent",
        )

        assert rejected is not None
        assert len(scheduled) == 1
        await _launch_workspace_retry_attempt(**scheduled[0])

        attempts = (
            await test_db.execute(
                select(WorkspaceTaskSessionAttemptModel)
                .where(WorkspaceTaskSessionAttemptModel.workspace_task_id == child_task.id)
                .order_by(WorkspaceTaskSessionAttemptModel.attempt_number.asc())
            )
        ).scalars().all()
        assert len(attempts) == 2
        assert attempts[0].status == "rejected"
        assert attempts[1].status == "awaiting_leader_adjudication"
        assert attempts[1].candidate_summary == "Retry candidate completed"
        assert attempts[1].conversation_id == captured["conversation_id"]

        await test_db.refresh(child_task)
        assert child_task.metadata_json["current_attempt_id"] == attempts[1].id
        assert child_task.metadata_json["pending_leader_adjudication"] is True
        assert child_task.metadata_json["last_worker_report_summary"] == "Retry candidate completed"

        accepted = await adjudicate_workspace_worker_report(
            workspace_id=workspace.id,
            task_id=child_task.id,
            actor_user_id=user.id,
            status=WorkspaceTaskStatus.DONE,
            leader_agent_id="leader-agent",
        )

        assert accepted is not None

    await test_db.refresh(child_task)
    assert child_task.status == "done"
    attempts = (
        await test_db.execute(
            select(WorkspaceTaskSessionAttemptModel)
            .where(WorkspaceTaskSessionAttemptModel.workspace_task_id == child_task.id)
            .order_by(WorkspaceTaskSessionAttemptModel.attempt_number.asc())
        )
    ).scalars().all()
    assert attempts[1].status == "accepted"


@pytest.mark.asyncio
async def test_create_objective_auto_binds_builtin_leader_when_workspace_has_no_agents(
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
        email="ws-api-objective-autobind@example.com",
        hashed_password="hash",
        full_name="Owner",
        is_active=True,
    )
    tenant = Tenant(
        id="tenant-ws-api-objective-autobind",
        name="TenantObjectiveAutoBind",
        slug="tenant-ws-api-objective-autobind",
        description="tenant",
        owner_id=user.id,
        plan="free",
        max_projects=10,
        max_users=10,
        max_storage=1024,
    )
    project = Project(
        id="project-ws-api-objective-autobind",
        tenant_id=tenant.id,
        name="ProjectObjectiveAutoBind",
        description="project",
        owner_id=user.id,
        memory_rules={},
        graph_config={},
    )
    workspace = WorkspaceModel(
        id="workspace-api-objective-autobind",
        tenant_id=tenant.id,
        project_id=project.id,
        name="Workspace Objective AutoBind",
        created_by=user.id,
        metadata_json={},
    )
    membership = WorkspaceMemberModel(
        id="wm-api-objective-autobind",
        workspace_id=workspace.id,
        user_id=user.id,
        role="owner",
        invited_by=user.id,
    )
    user_tenant = UserTenant(
        id="ut-api-objective-autobind",
        user_id=user.id,
        tenant_id=tenant.id,
        role="owner",
        permissions={"admin": True, "read": True, "write": True},
    )
    user_project = UserProject(
        id="up-api-objective-autobind",
        user_id=user.id,
        project_id=project.id,
        role="owner",
    )

    test_db.add_all([user, tenant, project, workspace, membership, user_tenant, user_project])
    await test_db.commit()

    response = await client.post(
        f"/api/v1/tenants/{tenant.id}/projects/{project.id}/workspaces/{workspace.id}/objectives",
        json={"title": "Auto-bind leader objective", "obj_type": "objective"},
    )

    assert response.status_code == status.HTTP_201_CREATED
    binding = await test_db.scalar(
        select(WorkspaceAgentModel).where(WorkspaceAgentModel.workspace_id == workspace.id)
    )
    assert binding is not None
    assert binding.agent_id == BUILTIN_SISYPHUS_ID
    builtin_agent = await test_db.get(AgentDefinitionModel, BUILTIN_SISYPHUS_ID)
    assert builtin_agent is not None
    message = await test_db.scalar(
        select(WorkspaceMessageModel).where(WorkspaceMessageModel.workspace_id == workspace.id)
    )
    assert message is not None
    assert message.mentions_json == [BUILTIN_SISYPHUS_ID]
    assert message.metadata_json["conversation_scope"] == f"objective:{response.json()['id']}"
    triggered_message = triggered["message"]
    assert triggered_message.mentions == [BUILTIN_SISYPHUS_ID]


@pytest.mark.asyncio
async def test_create_objective_self_heals_legacy_sisyphus_name_conflict(
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
        email="ws-api-objective-autobind-conflict@example.com",
        hashed_password="hash",
        full_name="Owner",
        is_active=True,
    )
    tenant = Tenant(
        id="tenant-ws-api-objective-autobind-conflict",
        name="TenantObjectiveAutoBindConflict",
        slug="tenant-ws-api-objective-autobind-conflict",
        description="tenant",
        owner_id=user.id,
        plan="free",
        max_projects=10,
        max_users=10,
        max_storage=1024,
    )
    project = Project(
        id="project-ws-api-objective-autobind-conflict",
        tenant_id=tenant.id,
        name="ProjectObjectiveAutoBindConflict",
        description="project",
        owner_id=user.id,
        memory_rules={},
        graph_config={},
    )
    workspace = WorkspaceModel(
        id="workspace-api-objective-autobind-conflict",
        tenant_id=tenant.id,
        project_id=project.id,
        name="Workspace Objective AutoBind Conflict",
        created_by=user.id,
        metadata_json={},
    )
    membership = WorkspaceMemberModel(
        id="wm-api-objective-autobind-conflict",
        workspace_id=workspace.id,
        user_id=user.id,
        role="owner",
        invited_by=user.id,
    )
    conflicting_agent = AgentDefinitionModel(
        id="legacy-sisyphus-autobind",
        tenant_id=tenant.id,
        project_id=project.id,
        name="sisyphus",
        display_name="Legacy Sisyphus",
        system_prompt="Legacy builtin row",
        allowed_tools=[],
        allowed_skills=[],
        allowed_mcp_servers=[],
        source="database",
    )
    user_tenant = UserTenant(
        id="ut-api-objective-autobind-conflict",
        user_id=user.id,
        tenant_id=tenant.id,
        role="owner",
        permissions={"admin": True, "read": True, "write": True},
    )
    user_project = UserProject(
        id="up-api-objective-autobind-conflict",
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
            conflicting_agent,
            user_tenant,
            user_project,
        ]
    )
    await test_db.commit()

    response = await client.post(
        f"/api/v1/tenants/{tenant.id}/projects/{project.id}/workspaces/{workspace.id}/objectives",
        json={"title": "Auto-bind leader objective with conflict", "obj_type": "objective"},
    )

    assert response.status_code == status.HTTP_201_CREATED
    binding = await test_db.scalar(
        select(WorkspaceAgentModel).where(WorkspaceAgentModel.workspace_id == workspace.id)
    )
    assert binding is not None
    assert binding.agent_id == BUILTIN_SISYPHUS_ID
    builtin_agent = await test_db.get(AgentDefinitionModel, BUILTIN_SISYPHUS_ID)
    assert builtin_agent is not None
    await test_db.refresh(conflicting_agent)
    legacy_agent = conflicting_agent
    assert legacy_agent.name == f"sisyphus-legacy-{conflicting_agent.id}"
    assert legacy_agent.metadata_json["renamed_from_builtin_name"] == "sisyphus"
    assert legacy_agent.metadata_json["renamed_for_builtin_id"] == BUILTIN_SISYPHUS_ID
    message = await test_db.scalar(
        select(WorkspaceMessageModel).where(WorkspaceMessageModel.workspace_id == workspace.id)
    )
    assert message is not None
    assert message.mentions_json == [BUILTIN_SISYPHUS_ID]
    assert triggered["message"].mentions == [BUILTIN_SISYPHUS_ID]


@pytest.mark.asyncio
async def test_goal_candidates_self_heals_missing_leader_binding_and_triggers_existing_root(
    authenticated_async_client, test_db, monkeypatch
) -> None:
    client: AsyncClient = authenticated_async_client
    triggered: dict[str, object] = {}

    def _capture_fire(**kwargs: object) -> None:
        triggered.update(kwargs)

    monkeypatch.setattr(
        "src.infrastructure.adapters.primary.web.routers.workspace_leader_bootstrap._fire_mention_routing",
        _capture_fire,
    )

    user = User(
        id="550e8400-e29b-41d4-a716-446655440000",
        email="ws-api-goal-heal@example.com",
        hashed_password="hash",
        full_name="Owner",
        is_active=True,
    )
    tenant = Tenant(
        id="tenant-ws-api-goal-heal",
        name="TenantGoalHeal",
        slug="tenant-ws-api-goal-heal",
        description="tenant",
        owner_id=user.id,
        plan="free",
        max_projects=10,
        max_users=10,
        max_storage=1024,
    )
    project = Project(
        id="project-ws-api-goal-heal",
        tenant_id=tenant.id,
        name="ProjectGoalHeal",
        description="project",
        owner_id=user.id,
        memory_rules={},
        graph_config={},
    )
    workspace = WorkspaceModel(
        id="workspace-api-goal-heal",
        tenant_id=tenant.id,
        project_id=project.id,
        name="Workspace Goal Heal",
        created_by=user.id,
        metadata_json={},
    )
    membership = WorkspaceMemberModel(
        id="wm-api-goal-heal",
        workspace_id=workspace.id,
        user_id=user.id,
        role="owner",
        invited_by=user.id,
    )
    objective = CyberObjectiveModel(
        id="objective-api-goal-heal",
        workspace_id=workspace.id,
        title="Heal existing root",
        description="desc",
        obj_type="objective",
        parent_id=None,
        progress=0.0,
        created_by=user.id,
    )
    root_task = WorkspaceTaskModel(
        id="root-api-goal-heal",
        workspace_id=workspace.id,
        title="Heal existing root",
        created_by=user.id,
        status="todo",
        metadata_json={
            "autonomy_schema_version": 1,
            "task_role": "goal_root",
            "goal_origin": "existing_objective",
            "goal_source_refs": [f"objective:{objective.id}"],
            "goal_formalization_reason": "selected workspace objective projected into execution root",
            "objective_id": objective.id,
            "root_goal_policy": {
                "mutable_by_agent": False,
                "completion_requires_external_proof": True,
            },
            "goal_health": "healthy",
            "replan_attempt_count": 0,
            "last_mutation_actor": {
                "action": "create",
                "actor_type": "human",
                "actor_user_id": user.id,
                "reason": "workspace_task.create",
            },
        },
    )
    user_tenant = UserTenant(
        id="ut-api-goal-heal",
        user_id=user.id,
        tenant_id=tenant.id,
        role="owner",
        permissions={"admin": True, "read": True, "write": True},
    )
    user_project = UserProject(
        id="up-api-goal-heal",
        user_id=user.id,
        project_id=project.id,
        role="owner",
    )
    test_db.add_all([
        user, tenant, project, workspace, membership, objective, root_task, user_tenant, user_project
    ])
    await test_db.commit()

    response = await client.get(f"/api/v1/workspaces/{workspace.id}/goal-candidates")

    assert response.status_code == status.HTTP_200_OK
    binding = await test_db.scalar(
        select(WorkspaceAgentModel).where(WorkspaceAgentModel.workspace_id == workspace.id)
    )
    assert binding is not None
    assert binding.agent_id == BUILTIN_SISYPHUS_ID
    message = await test_db.scalar(
        select(WorkspaceMessageModel).where(WorkspaceMessageModel.workspace_id == workspace.id)
    )
    assert message is not None
    assert message.metadata_json["conversation_scope"] == f"objective:{objective.id}"
    assert message.mentions_json == [BUILTIN_SISYPHUS_ID]
    assert triggered["workspace_id"] == workspace.id
    triggered_message = triggered["message"]
    assert triggered_message.mentions == [BUILTIN_SISYPHUS_ID]


@pytest.mark.asyncio
async def test_goal_candidates_triggers_existing_root_when_agents_exist_but_no_bootstrap_message(
    authenticated_async_client, test_db, monkeypatch
) -> None:
    client: AsyncClient = authenticated_async_client
    triggered: dict[str, object] = {}

    def _capture_fire(**kwargs: object) -> None:
        triggered.update(kwargs)

    monkeypatch.setattr(
        "src.infrastructure.adapters.primary.web.routers.workspace_leader_bootstrap._fire_mention_routing",
        _capture_fire,
    )

    user = User(
        id="550e8400-e29b-41d4-a716-446655440000",
        email="ws-api-goal-existing-agents@example.com",
        hashed_password="hash",
        full_name="Owner",
        is_active=True,
    )
    tenant = Tenant(
        id="tenant-ws-api-goal-existing-agents",
        name="TenantGoalExistingAgents",
        slug="tenant-ws-api-goal-existing-agents",
        description="tenant",
        owner_id=user.id,
        plan="free",
        max_projects=10,
        max_users=10,
        max_storage=1024,
    )
    project = Project(
        id="project-ws-api-goal-existing-agents",
        tenant_id=tenant.id,
        name="ProjectGoalExistingAgents",
        description="project",
        owner_id=user.id,
        memory_rules={},
        graph_config={},
    )
    workspace = WorkspaceModel(
        id="workspace-api-goal-existing-agents",
        tenant_id=tenant.id,
        project_id=project.id,
        name="Workspace Goal Existing Agents",
        created_by=user.id,
        metadata_json={},
    )
    membership = WorkspaceMemberModel(
        id="wm-api-goal-existing-agents",
        workspace_id=workspace.id,
        user_id=user.id,
        role="owner",
        invited_by=user.id,
    )
    agent = AgentDefinitionModel(
        id="agent-api-goal-existing-agents",
        tenant_id=tenant.id,
        project_id=project.id,
        name="atlas-existing-agents",
        display_name="Atlas - Master Orchestrator",
        system_prompt="You lead execution.",
        allowed_tools=[],
        allowed_skills=[],
        allowed_mcp_servers=[],
    )
    binding = WorkspaceAgentModel(
        id="wa-api-goal-existing-agents",
        workspace_id=workspace.id,
        agent_id=agent.id,
        display_name="Atlas - Master Orchestrator",
        description=None,
        config_json={},
        is_active=True,
    )
    objective = CyberObjectiveModel(
        id="objective-api-goal-existing-agents",
        workspace_id=workspace.id,
        title="Existing agent root trigger",
        description="desc",
        obj_type="objective",
        parent_id=None,
        progress=0.0,
        created_by=user.id,
    )
    root_task = WorkspaceTaskModel(
        id="root-api-goal-existing-agents",
        workspace_id=workspace.id,
        title="Existing agent root trigger",
        created_by=user.id,
        status="todo",
        metadata_json={
            "autonomy_schema_version": 1,
            "task_role": "goal_root",
            "goal_origin": "existing_objective",
            "goal_source_refs": [f"objective:{objective.id}"],
            "goal_formalization_reason": "selected workspace objective projected into execution root",
            "objective_id": objective.id,
            "root_goal_policy": {
                "mutable_by_agent": False,
                "completion_requires_external_proof": True,
            },
            "goal_health": "healthy",
            "replan_attempt_count": 0,
        },
    )
    user_tenant = UserTenant(
        id="ut-api-goal-existing-agents",
        user_id=user.id,
        tenant_id=tenant.id,
        role="owner",
        permissions={"admin": True, "read": True, "write": True},
    )
    user_project = UserProject(
        id="up-api-goal-existing-agents",
        user_id=user.id,
        project_id=project.id,
        role="owner",
    )
    test_db.add_all([
        user, tenant, project, workspace, membership, agent, binding, objective, root_task, user_tenant, user_project
    ])
    await test_db.commit()

    response = await client.get(f"/api/v1/workspaces/{workspace.id}/goal-candidates")

    assert response.status_code == status.HTTP_200_OK
    message = await test_db.scalar(
        select(WorkspaceMessageModel).where(WorkspaceMessageModel.workspace_id == workspace.id)
    )
    assert message is not None
    assert message.metadata_json["conversation_scope"] == f"objective:{objective.id}"
    assert message.mentions_json == [agent.id]
    assert triggered["workspace_id"] == workspace.id
    assert triggered["message"].mentions == [agent.id]
