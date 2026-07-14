from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import status
from sqlalchemy import delete

from src.infrastructure.adapters.secondary.persistence.artifact_model import ArtifactModel
from src.infrastructure.adapters.secondary.persistence.models import (
    AgentTaskModel,
    Conversation,
    HITLRequest,
    PlanModel,
    PlanNodeModel,
    ToolExecutionRecord,
    WorkspaceMemberModel,
    WorkspaceModel,
    WorkspaceTaskModel,
    WorkspaceTaskSessionAttemptModel,
)


async def test_workspace_session_projection_is_scoped_and_omits_sensitive_runtime_fields(
    authenticated_async_client,
    test_db,
    test_project_db,
    test_user,
) -> None:
    now = datetime.now(UTC)
    workspace = WorkspaceModel(
        id="session-projection-workspace",
        tenant_id=test_project_db.tenant_id,
        project_id=test_project_db.id,
        name="Session projection workspace",
        created_by=test_user.id,
        metadata_json={},
    )
    member = WorkspaceMemberModel(
        id="session-projection-member",
        workspace_id=workspace.id,
        user_id=test_user.id,
        role="owner",
        invited_by=test_user.id,
    )
    task = WorkspaceTaskModel(
        id="session-projection-task",
        workspace_id=workspace.id,
        title="Project one conversation",
        created_by=test_user.id,
        status="in_progress",
        metadata_json={},
    )
    conversation = Conversation(
        id="session-projection-conversation",
        project_id=test_project_db.id,
        tenant_id=test_project_db.tenant_id,
        user_id=test_user.id,
        title="Scoped conversation",
        status="active",
        agent_config={"capability_mode": "code", "temperature": 0.25},
        meta={"private": "not projected"},
        message_count=2,
        current_mode="build",
        conversation_mode="autonomous",
        workspace_id=workspace.id,
        linked_workspace_task_id=task.id,
        participant_agents=["agent-worker"],
        coordinator_agent_id="agent-leader",
        focused_agent_id="agent-worker",
    )
    attempts = [
        WorkspaceTaskSessionAttemptModel(
            id="session-projection-attempt-1",
            workspace_task_id=task.id,
            root_goal_task_id=task.id,
            workspace_id=workspace.id,
            attempt_number=1,
            status="rejected",
            conversation_id=conversation.id,
            candidate_artifacts_json=["artifact://old"],
            candidate_verifications_json=["check://old"],
            created_at=now - timedelta(minutes=5),
        ),
        WorkspaceTaskSessionAttemptModel(
            id="session-projection-attempt-2",
            workspace_task_id=task.id,
            root_goal_task_id=task.id,
            workspace_id=workspace.id,
            attempt_number=2,
            status="running",
            conversation_id=conversation.id,
            worker_agent_id="agent-worker",
            leader_agent_id="agent-leader",
            candidate_summary="Current candidate",
            candidate_artifacts_json=["artifact://current"],
            candidate_verifications_json=["check://tests", "check://lint"],
            leader_feedback="Continue with the scoped implementation",
            created_at=now - timedelta(minutes=2),
        ),
    ]
    checklist = AgentTaskModel(
        id="session-projection-checklist",
        conversation_id=conversation.id,
        content="Write the endpoint",
        status="in_progress",
        priority="high",
        order_index=0,
    )
    plan = PlanModel(
        id="session-projection-plan",
        workspace_id=workspace.id,
        goal_id="session-projection-goal",
        status="active",
        created_at=now - timedelta(minutes=10),
    )
    linked_node = PlanNodeModel(
        id="session-projection-node",
        plan_id=plan.id,
        parent_id=plan.goal_id,
        kind="task",
        title="Project one conversation",
        description="Keep authority scoped",
        depends_on=[],
        acceptance_criteria=[{"kind": "command", "description": "Focused tests pass"}],
        intent="in_progress",
        execution="running",
        progress={"percent": 50},
        current_attempt_id=attempts[-1].id,
        workspace_task_id=task.id,
    )
    pending_hitl = HITLRequest(
        id="session-projection-hitl",
        request_type="decision",
        conversation_id=conversation.id,
        message_id="message-1",
        tenant_id=test_project_db.tenant_id,
        project_id=test_project_db.id,
        user_id=test_user.id,
        question="Choose the reviewed option",
        options=[
            {
                "id": "safe-option",
                "label": "Safe option",
                "value": "password=raw-option-secret",
            }
        ],
        context={"scope": "workspace", "password": "raw context secret"},
        request_metadata={"hitl_type": "decision", "internal": "not projected"},
        status="pending",
        response="response secret must not leak",
        response_metadata={"sealed_response": "ciphertext must not leak"},
        created_at=now - timedelta(minutes=1),
        expires_at=now + timedelta(minutes=5),
    )
    expired_hitl = HITLRequest(
        id="session-projection-expired-hitl",
        request_type="clarification",
        conversation_id=conversation.id,
        tenant_id=test_project_db.tenant_id,
        project_id=test_project_db.id,
        user_id=test_user.id,
        question="Expired request",
        status="pending",
        created_at=now - timedelta(minutes=10),
        expires_at=now - timedelta(minutes=1),
    )
    tool_record = ToolExecutionRecord(
        id="session-projection-tool",
        conversation_id=conversation.id,
        message_id="message-1",
        call_id="call-1",
        tool_name="read_file",
        tool_input={"token": "raw input secret"},
        tool_output="raw output secret",
        status="success",
        error="password=raw-tool-error-secret",
        sequence_number=1,
        started_at=now - timedelta(seconds=30),
        completed_at=now - timedelta(seconds=29),
        duration_ms=1000,
    )
    artifact = ArtifactModel(
        id="session-projection-artifact",
        project_id=test_project_db.id,
        tenant_id=test_project_db.tenant_id,
        conversation_id=conversation.id,
        workspace_id=workspace.id,
        filename="report.md",
        mime_type="text/markdown",
        category="document",
        size_bytes=12,
        object_key="session-projection/report.md",
        status="ready",
    )
    artifact_outside_workspace_scope = ArtifactModel(
        id="session-projection-artifact-outside-workspace",
        project_id=test_project_db.id,
        tenant_id=test_project_db.tenant_id,
        conversation_id=conversation.id,
        workspace_id=None,
        filename="outside.md",
        mime_type="text/markdown",
        category="document",
        size_bytes=7,
        object_key="session-projection/outside.md",
        status="ready",
    )
    test_db.add_all(
        [
            workspace,
            member,
            task,
            conversation,
            *attempts,
            checklist,
            plan,
            linked_node,
            pending_hitl,
            expired_hitl,
            tool_record,
            artifact,
            artifact_outside_workspace_scope,
        ]
    )
    await test_db.commit()

    response = await authenticated_async_client.get(
        f"/api/v1/agent/conversations/{conversation.id}/session",
        params={
            "tenant_id": test_project_db.tenant_id,
            "project_id": test_project_db.id,
            "workspace_id": workspace.id,
        },
    )

    assert response.status_code == status.HTTP_200_OK
    payload = response.json()
    assert payload["schema_version"] == 2
    assert payload["projection_kind"] == "workspace_session"
    assert payload["authority_kind"] == "workspace_attempt"
    assert payload["authority_id"] == attempts[-1].id
    assert payload["conversation"]["capability_mode"] == "code"
    assert payload["conversation"]["workspace_name"] == workspace.name
    assert [item["id"] for item in payload["execution"]["attempt_history"]] == [
        attempts[-1].id,
        attempts[0].id,
    ]
    assert payload["conversation_tasks"][0]["id"] == checklist.id
    assert payload["workspace_plan_context"]["id"] == plan.id
    assert payload["workspace_plan_context"]["linked_nodes"][0] == {
        "id": linked_node.id,
        "plan_id": plan.id,
        "workspace_task_id": task.id,
        "kind": "task",
        "title": "Project one conversation",
        "description": "Keep authority scoped",
        "intent": "in_progress",
        "execution": "running",
        "progress": {"percent": 50},
        "assignee_agent_id": None,
        "current_attempt_id": attempts[-1].id,
        "created_at": linked_node.created_at.replace(tzinfo=UTC).isoformat().replace("+00:00", "Z"),
        "updated_at": None,
        "completed_at": None,
    }
    assert [item["id"] for item in payload["pending_hitl"]] == [pending_hitl.id]
    assert payload["pending_hitl"][0]["request_type"] == "decision"
    assert payload["pending_hitl"][0]["question"] == "Choose the reviewed option"
    assert payload["pending_hitl"][0]["options"] == [{"id": "safe-option", "label": "Safe option"}]
    assert payload["pending_hitl"][0]["context"] == {}
    assert payload["pending_hitl"][0]["metadata"] == {"hitl_type": "decision"}
    assert payload["capabilities"]["can_send_message"] is False
    assert payload["capabilities"]["can_respond_to_hitl"] is True
    assert payload["capabilities"]["allowed_actions"] == ["respond_to_hitl"]
    assert payload["artifact_records"] == [{"id": artifact.id}]
    assert payload["evidence_summary"]["artifact_record_count"] == 1
    assert payload["tool_execution_records"]["items"][0] == {
        "id": tool_record.id,
        "message_id": "message-1",
        "call_id": "call-1",
        "tool_name": "read_file",
        "status": "success",
        "error": None,
        "step_number": None,
        "sequence_number": 1,
        "started_at": tool_record.started_at.isoformat().replace("+00:00", "Z"),
        "completed_at": tool_record.completed_at.isoformat().replace("+00:00", "Z"),
        "duration_ms": 1000,
    }
    serialized = response.text
    for secret in (
        "raw input secret",
        "raw output secret",
        "response secret must not leak",
        "ciphertext must not leak",
        "not projected",
        "raw context secret",
        "raw-option-secret",
        "raw-tool-error-secret",
    ):
        assert secret not in serialized
    for fabricated in (
        '"run_id"',
        '"revision"',
        '"permission_profile"',
        '"environment"',
        '"plan_version"',
        '"artifact_version"',
    ):
        assert fabricated not in serialized

    for bad_scope in (
        {
            "tenant_id": "wrong-tenant",
            "project_id": test_project_db.id,
            "workspace_id": workspace.id,
        },
        {
            "tenant_id": test_project_db.tenant_id,
            "project_id": "wrong-project",
            "workspace_id": workspace.id,
        },
        {
            "tenant_id": test_project_db.tenant_id,
            "project_id": test_project_db.id,
            "workspace_id": "wrong-workspace",
        },
        {
            "tenant_id": test_project_db.tenant_id,
            "project_id": test_project_db.id,
        },
    ):
        denied = await authenticated_async_client.get(
            f"/api/v1/agent/conversations/{conversation.id}/session",
            params=bad_scope,
        )
        assert denied.status_code == status.HTTP_404_NOT_FOUND

    await test_db.execute(delete(WorkspaceMemberModel).where(WorkspaceMemberModel.id == member.id))
    await test_db.commit()
    denied = await authenticated_async_client.get(
        f"/api/v1/agent/conversations/{conversation.id}/session",
        params={
            "tenant_id": test_project_db.tenant_id,
            "project_id": test_project_db.id,
            "workspace_id": workspace.id,
        },
    )
    assert denied.status_code == status.HTTP_404_NOT_FOUND


async def test_standalone_session_projection_allows_omitted_workspace(
    authenticated_async_client,
    test_db,
    test_project_db,
    test_user,
) -> None:
    conversation = Conversation(
        id="standalone-session-projection",
        project_id=test_project_db.id,
        tenant_id=test_project_db.tenant_id,
        user_id=test_user.id,
        title="Standalone session",
        status="active",
        agent_config={},
        message_count=0,
        current_mode="plan",
        conversation_mode="single_agent",
        workspace_id=None,
        linked_workspace_task_id=None,
    )
    test_db.add(conversation)
    await test_db.commit()

    response = await authenticated_async_client.get(
        f"/api/v1/agent/conversations/{conversation.id}/session",
        params={
            "tenant_id": test_project_db.tenant_id,
            "project_id": test_project_db.id,
        },
    )

    assert response.status_code == status.HTTP_200_OK
    assert response.json()["authority_kind"] == "conversation_record"
