from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from fastapi import status
from sqlalchemy import delete

from src.infrastructure.adapters.secondary.persistence.models import (
    AgentPlanRunModel,
    AgentPlanVersionModel,
    AgentRunSummaryModel,
    Conversation,
    HITLRequest,
    UserProject,
    UserTenant,
)


async def test_my_work_embeds_authoritative_agent_run_summary(
    authenticated_async_client,
    test_db,
    test_project_db,
    test_user,
) -> None:
    now = datetime.now(UTC)
    # Workspace rows are Core-owned since c84f19b55; conversations keep the
    # workspace linkage as a plain foreign key string.
    conversation = Conversation(
        id="my-work-run-conversation",
        project_id=test_project_db.id,
        tenant_id=test_project_db.tenant_id,
        user_id=test_user.id,
        title="Agent run",
        status="active",
        agent_config={"capability_mode": "code"},
        message_count=0,
        workspace_id="my-work-run-workspace",
    )
    plan = AgentPlanVersionModel(
        id="my-work-run-plan",
        conversation_id=conversation.id,
        version=1,
        status="approved",
        tasks_json=[],
        approved_at=now,
    )
    run = AgentPlanRunModel(
        id="my-work-agent-run",
        conversation_id=conversation.id,
        project_id=test_project_db.id,
        plan_version_id=plan.id,
        idempotency_key="my-work-run-start",
        message_id="my-work-run-message",
        request_message="Implement",
        status="ready_review",
        revision=2,
        permission_profile="workspace_write",
        authorization_snapshot={"environment": {"id": "sandbox-1"}},
        created_at=now - timedelta(seconds=2),
        updated_at=now,
        completed_at=now,
    )
    summary = AgentRunSummaryModel(
        id="my-work-run-summary",
        tenant_id=test_project_db.tenant_id,
        project_id=test_project_db.id,
        conversation_id=conversation.id,
        run_id=run.id,
        status=run.status,
        revision=run.revision,
        summary_state="recorded",
        reason_code=None,
        started_at=now - timedelta(seconds=2),
        completed_at=now,
        duration_ms=2000,
        input_tokens=10,
        output_tokens=5,
        cost_usd=0.01,
        model_breakdown_json=[{"model": "model-a"}],
        completion_summary="Completed",
        artifact_count=1,
        checks_passed=2,
        checks_failed=0,
        files_changed=1,
        lines_added=3,
        lines_deleted=1,
        evidence_references_json=[{"kind": "trace", "value": "trace-1"}],
        created_at=now,
        updated_at=now,
    )
    test_db.add_all([conversation, plan, run, summary])
    await test_db.commit()

    response = await authenticated_async_client.get(
        f"/api/v1/projects/{test_project_db.id}/my-work"
    )

    assert response.status_code == status.HTTP_200_OK
    item = response.json()["items"][0]
    assert item["id"] == f"agent_run:{run.id}"
    assert item["status"] == "ready_review"
    assert item["run_summary"] == {
        "run_id": run.id,
        "tenant_id": test_project_db.tenant_id,
        "project_id": test_project_db.id,
        "conversation_id": conversation.id,
        "status": "ready_review",
        "revision": 2,
        "summary_state": "recorded",
        "reason_code": None,
        "started_at": (now - timedelta(seconds=2)).isoformat().replace("+00:00", "Z"),
        "completed_at": now.isoformat().replace("+00:00", "Z"),
        "duration_ms": 2000,
        "input_tokens": 10,
        "output_tokens": 5,
        "cost_usd": 0.01,
        "model_breakdown": [{"model": "model-a"}],
        "completion_summary": "Completed",
        "artifact_count": 1,
        "checks_passed": 2,
        "checks_failed": 0,
        "files_changed": 1,
        "lines_added": 3,
        "lines_deleted": 1,
        "evidence_references": [{"kind": "trace", "value": "trace-1"}],
    }


async def test_my_work_includes_unbound_agent_workspace_run(
    authenticated_async_client,
    test_db,
    test_project_db,
    test_user,
) -> None:
    now = datetime.now(UTC)
    conversation = Conversation(
        id="my-work-unbound-conversation",
        project_id=test_project_db.id,
        tenant_id=test_project_db.tenant_id,
        user_id=test_user.id,
        title="Unbound Agent Workspace run",
        status="active",
        agent_config={"capability_mode": "work"},
        message_count=1,
        workspace_id=None,
    )
    plan = AgentPlanVersionModel(
        id="my-work-unbound-plan",
        conversation_id=conversation.id,
        version=1,
        status="approved",
        tasks_json=[],
        approved_at=now,
    )
    run = AgentPlanRunModel(
        id="my-work-unbound-run",
        conversation_id=conversation.id,
        project_id=test_project_db.id,
        plan_version_id=plan.id,
        idempotency_key="my-work-unbound-start",
        message_id="my-work-unbound-message",
        request_message="Implement",
        status="ready_review",
        revision=2,
        permission_profile="read_only",
        authorization_snapshot={"environment": None},
        created_at=now - timedelta(seconds=2),
        updated_at=now,
        completed_at=now,
    )
    test_db.add_all([conversation, plan, run])
    await test_db.commit()

    response = await authenticated_async_client.get(
        f"/api/v1/projects/{test_project_db.id}/my-work"
    )

    assert response.status_code == status.HTTP_200_OK
    item = next(item for item in response.json()["items"] if item["authority_id"] == run.id)
    assert item["workspace_id"] is None
    assert item["workspace_name"] is None
    assert item["status"] == "ready_review"
    assert item["run_summary"]["summary_state"] == "partial"
    assert item["run_summary"]["reason_code"] == "summary_not_recorded"


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


async def test_my_work_projects_scoped_hitl_authorities_without_fabricated_run_fields(
    authenticated_async_client,
    test_db,
    test_project_db,
    test_user,
) -> None:
    now = datetime.now(UTC)

    # Legacy SQL workspace attempt projections are retired (Avernet Core is the
    # sole Workspace authority), so only HITL authorities are projected here.
    # Workspace rows themselves are Core-owned; conversations keep the linkage
    # as a plain foreign key string.
    def _conversation(conversation_id: str) -> Conversation:
        return Conversation(
            id=conversation_id,
            project_id=test_project_db.id,
            tenant_id=test_project_db.tenant_id,
            user_id=test_user.id,
            title=f"Session {conversation_id}",
            status="active",
            agent_config={},
            message_count=0,
            workspace_id="my-work-visible",
        )

    test_db.add_all(
        [
            _conversation("conversation-hitl"),
            _conversation("conversation-expired"),
            _conversation("conversation-permission"),
        ]
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
    assert payload["total"] == 2
    assert set(items) == {
        decision.id,
        permission.id,
    }
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
