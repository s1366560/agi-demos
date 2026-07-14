from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from fastapi import status
from sqlalchemy import delete, select

from src.infrastructure.adapters.secondary.persistence.models import (
    Conversation,
    HITLRequest,
    User,
    UserProject,
    UserTenant,
    WorkspaceMemberModel,
    WorkspaceModel,
    WorkspaceTaskModel,
    WorkspaceTaskSessionAttemptModel,
)


async def test_my_work_requires_project_and_tenant_membership(
    authenticated_async_client,
    test_db,
    test_project_db,
    test_user,
) -> None:
    await test_db.execute(
        delete(UserProject).where(
            UserProject.project_id == test_project_db.id,
            UserProject.user_id == test_user.id,
        )
    )
    await test_db.commit()

    response = await authenticated_async_client.get(
        f"/api/v1/projects/{test_project_db.id}/my-work"
    )
    assert response.status_code == status.HTTP_403_FORBIDDEN

    test_db.add(
        UserProject(
            id=str(uuid4()),
            project_id=test_project_db.id,
            user_id=test_user.id,
            role="owner",
        )
    )
    await test_db.commit()
    await test_db.execute(
        delete(UserTenant).where(
            UserTenant.tenant_id == test_project_db.tenant_id,
            UserTenant.user_id == test_user.id,
        )
    )
    await test_db.commit()

    response = await authenticated_async_client.get(
        f"/api/v1/projects/{test_project_db.id}/my-work"
    )
    assert response.status_code == status.HTTP_403_FORBIDDEN


async def test_my_work_projects_latest_scoped_authorities_without_fabricated_run_fields(  # noqa: PLR0915
    authenticated_async_client,
    test_db,
    test_project_db,
    test_user,
) -> None:
    now = datetime.now(UTC)
    workspace = WorkspaceModel(
        id="my-work-visible",
        tenant_id=test_project_db.tenant_id,
        project_id=test_project_db.id,
        name="Visible workspace",
        created_by=test_user.id,
        metadata_json={"capability_mode": "code"},
    )
    hidden_workspace = WorkspaceModel(
        id="my-work-hidden",
        tenant_id=test_project_db.tenant_id,
        project_id=test_project_db.id,
        name="Hidden workspace",
        created_by=test_user.id,
        metadata_json={},
    )
    membership = WorkspaceMemberModel(
        id="my-work-member",
        workspace_id=workspace.id,
        user_id=test_user.id,
        role="owner",
        invited_by=test_user.id,
    )
    test_db.add_all([workspace, hidden_workspace, membership])

    async def add_attempt(
        *,
        task_id: str,
        conversation_id: str,
        workspace_id: str = workspace.id,
        status_value: str,
        attempt_number: int,
        capability_mode: str | None = None,
        created_offset: int = 0,
    ) -> WorkspaceTaskSessionAttemptModel:
        task = await test_db.get(WorkspaceTaskModel, task_id)
        if task is None:
            task = WorkspaceTaskModel(
                id=task_id,
                workspace_id=workspace_id,
                title=f"Task {task_id}",
                created_by=test_user.id,
                status="in_progress",
                metadata_json={},
            )
            test_db.add(task)
        conversation = await test_db.get(Conversation, conversation_id)
        if conversation is None:
            conversation = Conversation(
                id=conversation_id,
                project_id=test_project_db.id,
                tenant_id=test_project_db.tenant_id,
                user_id=test_user.id,
                title=f"Session {conversation_id}",
                status="active",
                agent_config={"capability_mode": capability_mode} if capability_mode else {},
                message_count=0,
                workspace_id=workspace_id,
                linked_workspace_task_id=task_id,
            )
            test_db.add(conversation)
        authority = WorkspaceTaskSessionAttemptModel(
            id=f"{task_id}-attempt-{attempt_number}",
            workspace_task_id=task_id,
            root_goal_task_id=task_id,
            workspace_id=workspace_id,
            attempt_number=attempt_number,
            status=status_value,
            conversation_id=conversation_id,
            created_at=now + timedelta(seconds=created_offset),
        )
        test_db.add(authority)
        await test_db.flush()
        return authority

    await add_attempt(
        task_id="task-blocked",
        conversation_id="conversation-blocked",
        status_value="running",
        attempt_number=1,
        capability_mode="invalid",
        created_offset=-30,
    )
    blocked = await add_attempt(
        task_id="task-blocked",
        conversation_id="conversation-blocked",
        status_value="blocked",
        attempt_number=2,
        created_offset=-20,
    )
    await add_attempt(
        task_id="task-terminal",
        conversation_id="conversation-terminal",
        status_value="running",
        attempt_number=1,
        created_offset=-30,
    )
    await add_attempt(
        task_id="task-terminal",
        conversation_id="conversation-terminal",
        status_value="accepted",
        attempt_number=2,
        created_offset=-10,
    )
    await add_attempt(
        task_id="task-hitl",
        conversation_id="conversation-hitl",
        status_value="running",
        attempt_number=1,
        capability_mode="work",
    )
    expired_visible = await add_attempt(
        task_id="task-expired",
        conversation_id="conversation-expired",
        status_value="pending",
        attempt_number=1,
    )
    await add_attempt(
        task_id="task-permission",
        conversation_id="conversation-permission",
        status_value="running",
        attempt_number=1,
    )
    await add_attempt(
        task_id="task-hidden",
        conversation_id="conversation-hidden",
        workspace_id=hidden_workspace.id,
        status_value="running",
        attempt_number=1,
    )

    decision = HITLRequest(
        id="hitl-decision",
        request_type="decision",
        conversation_id="conversation-hitl",
        tenant_id=test_project_db.tenant_id,
        project_id=test_project_db.id,
        user_id=test_user.id,
        question="Sensitive decision text",
        options={"items": ["sensitive option"]},
        context={"secret": "must not leak"},
        request_metadata={},
        status="pending",
        created_at=now,
        expires_at=now + timedelta(minutes=5),
    )
    expired = HITLRequest(
        id="hitl-expired",
        request_type="permission",
        conversation_id="conversation-expired",
        tenant_id=test_project_db.tenant_id,
        project_id=test_project_db.id,
        user_id=test_user.id,
        question="Expired",
        status="pending",
        created_at=now - timedelta(minutes=10),
        expires_at=now - timedelta(minutes=1),
    )
    permission = HITLRequest(
        id="hitl-permission",
        request_type="decision",
        conversation_id="conversation-permission",
        tenant_id=test_project_db.tenant_id,
        project_id=test_project_db.id,
        user_id=test_user.id,
        question="Approve operation",
        request_metadata={"hitl_type": "permission"},
        status="pending",
        created_at=now + timedelta(seconds=1),
        expires_at=now + timedelta(minutes=5),
    )
    answered = HITLRequest(
        id="hitl-answered",
        request_type="clarification",
        conversation_id="conversation-expired",
        tenant_id=test_project_db.tenant_id,
        project_id=test_project_db.id,
        user_id=test_user.id,
        question="Already answered",
        status="answered",
        created_at=now + timedelta(seconds=2),
        expires_at=now + timedelta(minutes=5),
    )
    test_db.add_all([decision, expired, permission, answered])
    await test_db.commit()

    response = await authenticated_async_client.get(
        f"/api/v1/projects/{test_project_db.id}/my-work"
    )

    assert response.status_code == status.HTTP_200_OK
    payload = response.json()
    items = {item["authority_id"]: item for item in payload["items"]}
    assert payload["total"] == 4
    assert set(items) == {
        blocked.id,
        expired_visible.id,
        decision.id,
        permission.id,
    }
    assert (
        items[blocked.id]
        | {
            "group": "needs_input",
            "status": "failed",
            "required_action": "inspect_failure",
            "capability_mode": "code",
            "attempt_number": 2,
        }
        == items[blocked.id]
    )
    assert items[expired_visible.id]["authority_kind"] == "workspace_attempt"
    assert items[decision.id]["authority_kind"] == "hitl_request"
    assert items[decision.id]["group"] == "needs_input"
    assert items[decision.id]["required_action"] == "provide_input"
    assert items[permission.id]["group"] == "needs_approval"
    assert items[permission.id]["status"] == "needs_approval"
    assert items[permission.id]["required_action"] == "review_approval"
    assert "question" not in items[decision.id]
    assert "options" not in items[decision.id]
    assert "context" not in items[decision.id]
    for item in items.values():
        assert item["run_id"] is None
        assert item["revision"] is None
        assert item["permission_profile"] is None
        assert item["environment"] is None
        assert item["last_heartbeat_at"] is None


async def test_my_work_excludes_workspace_without_membership(
    authenticated_async_client,
    test_db,
    test_project_db,
    test_user,
) -> None:
    workspace = WorkspaceModel(
        id="my-work-no-member",
        tenant_id=test_project_db.tenant_id,
        project_id=test_project_db.id,
        name="No membership",
        created_by=test_user.id,
        metadata_json={},
    )
    task = WorkspaceTaskModel(
        id="my-work-no-member-task",
        workspace_id=workspace.id,
        title="Hidden task",
        created_by=test_user.id,
        status="in_progress",
        metadata_json={},
    )
    conversation = Conversation(
        id="my-work-no-member-conversation",
        project_id=test_project_db.id,
        tenant_id=test_project_db.tenant_id,
        user_id=test_user.id,
        title="Hidden session",
        status="active",
        agent_config={"capability_mode": "work"},
        message_count=0,
        workspace_id=workspace.id,
        linked_workspace_task_id=task.id,
    )
    attempt_authority = WorkspaceTaskSessionAttemptModel(
        id="my-work-no-member-attempt",
        workspace_task_id=task.id,
        root_goal_task_id=task.id,
        workspace_id=workspace.id,
        attempt_number=1,
        status="running",
        conversation_id=conversation.id,
    )
    test_db.add_all([workspace, task, conversation, attempt_authority])
    await test_db.commit()

    response = await authenticated_async_client.get(
        f"/api/v1/projects/{test_project_db.id}/my-work"
    )

    assert response.status_code == status.HTTP_200_OK
    assert response.json() == {"project_id": test_project_db.id, "items": [], "total": 0}


async def test_my_work_reader_scopes_conversation_owner(
    authenticated_async_client,
    test_db,
    test_project_db,
    test_user,
) -> None:
    workspace = WorkspaceModel(
        id="my-work-owner-scope",
        tenant_id=test_project_db.tenant_id,
        project_id=test_project_db.id,
        name="Owner scope",
        created_by=test_user.id,
        metadata_json={},
    )
    member = WorkspaceMemberModel(
        id="my-work-owner-scope-member",
        workspace_id=workspace.id,
        user_id=test_user.id,
        role="owner",
    )
    task = WorkspaceTaskModel(
        id="my-work-owner-scope-task",
        workspace_id=workspace.id,
        title="Other owner's task",
        created_by=test_user.id,
        status="in_progress",
        metadata_json={},
    )
    other_user_id = "my-work-other-owner"
    other_user = User(
        id=other_user_id,
        email="my-work-other-owner@example.com",
        hashed_password="hash",
        full_name="Other owner",
        is_active=True,
    )
    visible_conversation = Conversation(
        id="my-work-owner-scope-visible-conversation",
        project_id=test_project_db.id,
        tenant_id=test_project_db.tenant_id,
        user_id=test_user.id,
        title="Older visible session",
        status="active",
        agent_config={"capability_mode": "work"},
        message_count=0,
        workspace_id=workspace.id,
        linked_workspace_task_id=task.id,
    )
    visible_attempt = WorkspaceTaskSessionAttemptModel(
        id="my-work-owner-scope-visible-attempt",
        workspace_task_id=task.id,
        root_goal_task_id=task.id,
        workspace_id=workspace.id,
        attempt_number=1,
        status="running",
        conversation_id=visible_conversation.id,
    )
    conversation = Conversation(
        id="my-work-owner-scope-conversation",
        project_id=test_project_db.id,
        tenant_id=test_project_db.tenant_id,
        user_id=other_user_id,
        title="Other owner's session",
        status="active",
        agent_config={"capability_mode": "code"},
        message_count=0,
        workspace_id=workspace.id,
        linked_workspace_task_id=task.id,
    )
    attempt_authority = WorkspaceTaskSessionAttemptModel(
        id="my-work-owner-scope-attempt",
        workspace_task_id=task.id,
        root_goal_task_id=task.id,
        workspace_id=workspace.id,
        attempt_number=2,
        status="running",
        conversation_id=conversation.id,
    )
    test_db.add_all(
        [
            other_user,
            workspace,
            member,
            task,
            visible_conversation,
            visible_attempt,
            conversation,
            attempt_authority,
        ]
    )
    await test_db.commit()

    result = await test_db.execute(
        select(UserProject.id).where(UserProject.user_id == test_user.id)
    )
    assert result.scalar_one_or_none() is not None
    response = await authenticated_async_client.get(
        f"/api/v1/projects/{test_project_db.id}/my-work"
    )
    assert response.status_code == status.HTTP_200_OK
    assert response.json()["items"] == []
