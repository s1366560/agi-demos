from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import status
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.ports.services.workspace_authority_port import (
    WorkspaceAuthorityAccessDeniedError,
    WorkspaceAuthorityProfile,
    WorkspaceAuthorityUnavailableError,
)
from src.infrastructure.adapters.secondary.persistence.artifact_model import ArtifactModel
from src.infrastructure.adapters.secondary.persistence.models import (
    AgentPlanRunModel,
    AgentPlanVersionModel,
    AgentTaskModel,
    Conversation,
    HITLRequest,
    ToolExecutionRecord,
)
from src.infrastructure.adapters.secondary.persistence.sql_agent_run_authority import (
    ensure_plan_run_authority,
)


class _ProjectionWorkspaceAuthority:
    def __init__(
        self,
        *,
        profiles: dict[str, WorkspaceAuthorityProfile] | None = None,
        task_links: set[tuple[str, str]] | None = None,
    ) -> None:
        self.profiles = profiles or {}
        self.task_links = task_links or set()

    async def get_profile(self, scope: object) -> WorkspaceAuthorityProfile:
        profile = self.profiles.get(str(scope.workspace_id))
        if profile is None:
            raise WorkspaceAuthorityAccessDeniedError
        return profile

    async def has_task(self, scope: object, task_id: str) -> bool:
        return (str(scope.workspace_id), task_id) in self.task_links


def _workspace_profile(
    *,
    workspace_id: str,
    tenant_id: str,
    project_id: str,
    workspace_name: str,
    created_by: str,
) -> WorkspaceAuthorityProfile:
    return WorkspaceAuthorityProfile(
        workspace_id=workspace_id,
        tenant_id=tenant_id,
        project_id=project_id,
        name=workspace_name,
        created_by=created_by,
        is_archived=False,
        metadata={"authority": "avernet"},
    )


async def _commit_plan_run_authority(
    db: AsyncSession,
    *,
    plan_run: AgentPlanRunModel,
    tenant_id: str,
) -> None:
    await db.flush()
    await ensure_plan_run_authority(db, run=plan_run, tenant_id=tenant_id)
    await db.commit()


def _assert_current_run(
    payload: dict[str, Any],
    *,
    plan_run: AgentPlanRunModel,
    conversation_id: str,
    project_id: str,
    plan_version_id: str,
) -> None:
    assert payload["schema_version"] == 2
    assert payload["projection_kind"] == "workspace_session"
    assert payload["authority_kind"] == "conversation_record"
    assert payload["authority_id"] == conversation_id
    current_run = payload["execution"]["current_run"]
    assert current_run == payload["execution"]["run_history"][0]
    assert current_run["id"] == plan_run.id
    assert current_run["revision"] == 2
    assert current_run["permission_profile"] == "full_access"
    assert current_run["environment"]["id"] == "session-projection-sandbox"
    assert current_run["environment"]["workspace_path"] == "/workspace"
    assert current_run["authorization_snapshot"] == {
        "conversation_id": conversation_id,
        "project_id": project_id,
        "plan_version_id": plan_version_id,
        "permission_profile": "full_access",
        "environment": current_run["environment"],
    }


def _assert_agent_plan_projection(
    payload: dict[str, Any],
    *,
    plan: AgentPlanVersionModel,
    conversation_id: str,
) -> None:
    assert payload["current_plan"] == payload["plan_history"][0]
    assert payload["current_plan"] == {
        "id": plan.id,
        "conversation_id": conversation_id,
        "version": plan.version,
        "status": plan.status,
        "tasks": plan.tasks_json,
        "created_at": plan.created_at.replace(tzinfo=UTC).isoformat().replace("+00:00", "Z"),
        "approved_at": plan.approved_at.isoformat().replace("+00:00", "Z"),
    }


def _assert_sensitive_runtime_fields_omitted(serialized: str) -> None:
    secrets = (
        "raw input secret",
        "raw output secret",
        "response secret must not leak",
        "ciphertext must not leak",
        "not projected",
        "raw context secret",
        "raw-option-secret",
        "raw-tool-error-secret",
    )
    assert all(secret not in serialized for secret in secrets)
    assert '"artifact_version"' not in serialized
    assert '"raw_authorization_secret"' not in serialized


async def _assert_projection_scopes_are_enforced(
    client: Any,
    *,
    conversation_id: str,
    tenant_id: str,
    project_id: str,
    workspace_id: str,
) -> None:
    bad_scopes = (
        {"tenant_id": "wrong-tenant", "project_id": project_id, "workspace_id": workspace_id},
        {"tenant_id": tenant_id, "project_id": "wrong-project", "workspace_id": workspace_id},
        {"tenant_id": tenant_id, "project_id": project_id, "workspace_id": "wrong-workspace"},
        {"tenant_id": tenant_id, "project_id": project_id},
    )
    for bad_scope in bad_scopes:
        denied = await client.get(
            f"/api/v1/agent/conversations/{conversation_id}/session",
            params=bad_scope,
        )
        assert denied.status_code == status.HTTP_404_NOT_FOUND


def _projection_authority(
    *,
    workspace_id: str,
    tenant_id: str,
    project_id: str,
    workspace_name: str,
    created_by: str,
    task_id: str,
) -> _ProjectionWorkspaceAuthority:
    return _ProjectionWorkspaceAuthority(
        profiles={
            workspace_id: _workspace_profile(
                workspace_id=workspace_id,
                tenant_id=tenant_id,
                project_id=project_id,
                workspace_name=workspace_name,
                created_by=created_by,
            )
        },
        task_links={(workspace_id, task_id)},
    )


async def test_workspace_session_projection_is_scoped_and_omits_sensitive_runtime_fields(
    authenticated_async_client,
    test_app,
    test_db,
    test_project_db,
    test_user,
) -> None:
    now = datetime.now(UTC)
    workspace_id = "session-projection-workspace"
    workspace_name = "Session projection workspace"
    task_id = "session-projection-task"
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
        workspace_id=workspace_id,
        linked_workspace_task_id=task_id,
        participant_agents=["agent-worker"],
        coordinator_agent_id="agent-leader",
        focused_agent_id="agent-worker",
    )
    approved_plan = AgentPlanVersionModel(
        id="session-projection-plan-version",
        conversation_id=conversation.id,
        version=1,
        status="approved",
        tasks_json=[],
        approved_at=now - timedelta(minutes=3),
    )
    plan_run = AgentPlanRunModel(
        id="session-projection-run",
        conversation_id=conversation.id,
        project_id=test_project_db.id,
        plan_version_id=approved_plan.id,
        idempotency_key="session-projection-approval",
        message_id="session-projection-message",
        request_message="Implement the scoped projection",
        status="running",
        revision=2,
        permission_profile="full_access",
        authorization_snapshot={
            "conversation_id": conversation.id,
            "project_id": test_project_db.id,
            "plan_version_id": approved_plan.id,
            "permission_profile": "full_access",
            "environment": {
                "id": "session-projection-sandbox",
                "kind": "worktree",
                "label": "session-projection-sandbox",
                "workspace_path": "/workspace",
                "repository_root": None,
                "branch": None,
                "base_commit": None,
                "source_run_id": None,
                "created_at": (now - timedelta(minutes=3)).isoformat(),
            },
            "raw_authorization_secret": "not projected",
        },
        created_at=now - timedelta(minutes=3),
        updated_at=now - timedelta(seconds=10),
    )
    checklist = AgentTaskModel(
        id="session-projection-checklist",
        conversation_id=conversation.id,
        content="Write the endpoint",
        title="Write the endpoint",
        status="in_progress",
        priority="high",
        order_index=0,
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
        workspace_id=workspace_id,
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
            conversation,
            approved_plan,
            plan_run,
            checklist,
            pending_hitl,
            expired_hitl,
            tool_record,
            artifact,
            artifact_outside_workspace_scope,
        ]
    )
    await _commit_plan_run_authority(
        test_db,
        plan_run=plan_run,
        tenant_id=test_project_db.tenant_id,
    )
    authority = _projection_authority(
        workspace_id=workspace_id,
        tenant_id=test_project_db.tenant_id,
        project_id=test_project_db.id,
        workspace_name=workspace_name,
        created_by=test_user.id,
        task_id=task_id,
    )
    test_app.state.workspace_authority = authority

    response = await authenticated_async_client.get(
        f"/api/v1/agent/conversations/{conversation.id}/session",
        params={
            "tenant_id": test_project_db.tenant_id,
            "project_id": test_project_db.id,
            "workspace_id": workspace_id,
        },
    )

    assert response.status_code == status.HTTP_200_OK
    payload = response.json()
    assert payload["conversation"]["capability_mode"] == "code"
    assert payload["conversation"]["workspace_name"] == workspace_name
    assert payload["execution"]["attempt_history"] == []
    _assert_current_run(
        payload,
        plan_run=plan_run,
        conversation_id=conversation.id,
        project_id=test_project_db.id,
        plan_version_id=approved_plan.id,
    )
    assert payload["conversation_tasks"][0]["id"] == checklist.id
    _assert_agent_plan_projection(
        payload,
        plan=approved_plan,
        conversation_id=conversation.id,
    )
    assert payload["workspace_plan_context"] is None
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
    _assert_sensitive_runtime_fields_omitted(response.text)
    await _assert_projection_scopes_are_enforced(
        authenticated_async_client,
        conversation_id=conversation.id,
        tenant_id=test_project_db.tenant_id,
        project_id=test_project_db.id,
        workspace_id=workspace_id,
    )

    core_access_does_not_depend_on_legacy_members = await authenticated_async_client.get(
        f"/api/v1/agent/conversations/{conversation.id}/session",
        params={
            "tenant_id": test_project_db.tenant_id,
            "project_id": test_project_db.id,
            "workspace_id": workspace_id,
        },
    )
    assert core_access_does_not_depend_on_legacy_members.status_code == status.HTTP_200_OK

    authority.profiles.clear()
    denied = await authenticated_async_client.get(
        f"/api/v1/agent/conversations/{conversation.id}/session",
        params={
            "tenant_id": test_project_db.tenant_id,
            "project_id": test_project_db.id,
            "workspace_id": workspace_id,
        },
    )
    assert denied.status_code == status.HTTP_404_NOT_FOUND


async def test_workspace_session_projection_fails_closed_when_core_is_unavailable(
    authenticated_async_client,
    test_app,
    test_db,
    test_project_db,
    test_user,
) -> None:
    workspace_id = "session-projection-core-unavailable-workspace"
    conversation = Conversation(
        id="session-projection-core-unavailable-conversation",
        project_id=test_project_db.id,
        tenant_id=test_project_db.tenant_id,
        user_id=test_user.id,
        title="Core unavailable",
        status="active",
        agent_config={},
        message_count=0,
        current_mode="plan",
        conversation_mode="single_agent",
        workspace_id=workspace_id,
        linked_workspace_task_id=None,
    )
    test_db.add(conversation)
    await test_db.commit()

    class _UnavailableAuthority:
        async def get_profile(self, _scope: object) -> WorkspaceAuthorityProfile:
            raise WorkspaceAuthorityUnavailableError

    test_app.state.workspace_authority = _UnavailableAuthority()

    response = await authenticated_async_client.get(
        f"/api/v1/agent/conversations/{conversation.id}/session",
        params={
            "tenant_id": test_project_db.tenant_id,
            "project_id": test_project_db.id,
            "workspace_id": workspace_id,
        },
    )

    assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
    assert response.json() == {
        "detail": {
            "code": "WORKSPACE_CORE_UNAVAILABLE",
            "reason": "workspace_core_unavailable",
            "detail": "Workspace Core is unavailable",
        }
    }


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
