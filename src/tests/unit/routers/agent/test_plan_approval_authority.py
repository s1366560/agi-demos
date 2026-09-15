"""Versioned approval must reject stale or busy conversation authority."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.adapters.primary.web.routers.agent import plans
from src.infrastructure.adapters.secondary.persistence.models import (
    AgentPlanVersionModel,
    AgentRunAuthorityModel,
    Conversation,
    HITLRequest,
    Project,
    User,
    UserProject,
    UserTenant,
)


@pytest.mark.unit
@pytest.mark.parametrize(
    "condition", ["queued", "running", "hitl", "stale", "scope", "project_member", "tenant_member"]
)
async def test_versioned_approval_rejects_invalid_authority(
    condition: str,
    monkeypatch: pytest.MonkeyPatch,
    test_db: AsyncSession,
    test_user: User,
    test_project_db: Project,
) -> None:
    conversation = Conversation(
        id="approval-authority-conversation",
        project_id=test_project_db.id,
        tenant_id=test_project_db.tenant_id,
        user_id=test_user.id,
        title="Approval authority",
        current_mode="plan",
    )
    test_db.add(conversation)
    await test_db.flush()
    plan = AgentPlanVersionModel(
        id="approval-authority-plan",
        conversation_id=conversation.id,
        version=2,
        status="draft",
        tasks_json=[],
    )
    test_db.add(plan)
    if condition in {"queued", "running"}:
        test_db.add(
            AgentRunAuthorityModel(
                id="existing-chat",
                tenant_id=conversation.tenant_id,
                project_id=conversation.project_id,
                conversation_id=conversation.id,
                run_kind="chat",
                idempotency_key="existing",
                message_id="existing",
                request_message="Existing execution",
                status=condition,
                permission_profile="read_only",
                authorization_snapshot={},
            )
        )
    if condition == "hitl":
        test_db.add(
            HITLRequest(
                id="pending-approval-hitl",
                tenant_id=conversation.tenant_id,
                project_id=conversation.project_id,
                conversation_id=conversation.id,
                request_type="decision",
                question="Pending decision",
                status="pending",
                expires_at=datetime.now(UTC) + timedelta(hours=1),
            )
        )
    await test_db.commit()
    if condition == "project_member":
        await test_db.execute(delete(UserProject).where(UserProject.user_id == test_user.id))
    if condition == "tenant_member":
        await test_db.execute(delete(UserTenant).where(UserTenant.user_id == test_user.id))
    await test_db.commit()
    resolve = AsyncMock(return_value={})
    execute = AsyncMock()
    monkeypatch.setattr(plans, "_resolve_cloud_run_environment", resolve)
    monkeypatch.setattr(plans, "_execute_approved_plan", execute)
    body = plans.ApprovePlanAndStartRequest(
        conversation_id=conversation.id,
        project_id="other-project" if condition == "scope" else conversation.project_id,
        plan_version_id=plan.id,
        expected_plan_version=1 if condition == "stale" else 2,
        permission_profile="read_only",
        message="Approve",
        message_id="new-message",
        idempotency_key="new-approval",
        environment={"kind": "local"},
    )
    with pytest.raises(HTTPException) as error:
        await plans.approve_plan_and_start(
            body,
            SimpleNamespace(),
            current_user=test_user,
            db=test_db,
        )
    assert error.value.status_code == (
        404 if condition in {"scope", "project_member", "tenant_member"} else 409
    )
    assert plan.status == "draft"
    resolve.assert_not_awaited()
    execute.assert_not_awaited()


@pytest.mark.unit
async def test_approval_freezes_selected_workspace_provider_config(
    monkeypatch, test_db, test_user, test_project_db
):
    import asyncio

    conversation = Conversation(
        id="policy-approval",
        tenant_id=test_project_db.tenant_id,
        project_id=test_project_db.id,
        user_id=test_user.id,
        title="Policy approval",
        workspace_id="workspace-1",
        current_mode="plan",
        agent_config={"capability_mode": "code"},
    )
    test_db.add(conversation)
    await test_db.flush()
    plan = AgentPlanVersionModel(
        id="policy-plan", conversation_id=conversation.id, version=3, status="draft", tasks_json=[]
    )
    test_db.add(plan)
    await test_db.commit()
    selected = {"provider_id": "specific-provider-account", "model_id": "selected-model"}
    monkeypatch.setattr(
        plans,
        "_load_workspace_policy_snapshot",
        AsyncMock(return_value=({"revision": 7, "roles": {"coding": selected}}, "read_only")),
    )
    monkeypatch.setattr(
        plans, "_resolve_cloud_run_environment", AsyncMock(return_value={"id": "environment"})
    )
    execute = AsyncMock()
    monkeypatch.setattr(plans, "_execute_approved_plan", execute)
    body = plans.ApprovePlanAndStartRequest(
        conversation_id=conversation.id,
        project_id=conversation.project_id,
        plan_version_id=plan.id,
        expected_plan_version=3,
        permission_profile="read_only",
        message="Approve",
        message_id="policy-message",
        idempotency_key="policy-key",
        environment={"kind": "local"},
    )
    result = await plans.approve_plan_and_start(body, SimpleNamespace(), test_user, test_db)
    await asyncio.sleep(0)
    canonical = await test_db.get(AgentRunAuthorityModel, result["run"]["id"])
    assert canonical.authorization_snapshot["model_route"] == selected
    assert canonical.authorization_snapshot["policy"]["revision"] == 7
    replay = await plans.approve_plan_and_start(body, SimpleNamespace(), test_user, test_db)
    assert replay["created"] is False
    assert replay["run"]["authorization_snapshot"]["model_route"] == selected
    execute.assert_awaited_once()
