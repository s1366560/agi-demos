"""Approval request authority and durable idempotency must remain exact."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from src.infrastructure.adapters.primary.web.routers.agent import plans
from src.infrastructure.adapters.secondary.persistence.models import (
    AgentPlanRunModel,
    AgentPlanVersionModel,
    AgentRunAuthorityModel,
    Conversation,
)


async def _approval_fixture(monkeypatch, test_db, test_user, test_project_db, policy_permission):
    conversation = Conversation(
        id="approval-request-conversation",
        tenant_id=test_project_db.tenant_id,
        project_id=test_project_db.id,
        user_id=test_user.id,
        title="Approval request contract",
        workspace_id="approval-workspace",
        current_mode="plan",
        agent_config={"capability_mode": "code"},
    )
    plan = AgentPlanVersionModel(
        id="approval-request-plan",
        conversation_id=conversation.id,
        version=1,
        status="draft",
        tasks_json=[],
    )
    test_db.add(conversation)
    await test_db.flush()
    test_db.add(plan)
    await test_db.commit()
    policy = {
        "revision": 1,
        "roles": {"coding": {"provider_id": "fixture-provider", "model_id": "fixture-model"}},
        "permission_mode": {
            "read_only": "ask",
            "workspace_write": "automatic",
            "full_access": "full_access",
        }[policy_permission],
    }
    monkeypatch.setattr(
        plans,
        "_load_workspace_policy_snapshot",
        AsyncMock(return_value=(policy, policy_permission)),
    )
    environment = AsyncMock(return_value={"id": "sandbox-fixture", "kind": "local"})
    monkeypatch.setattr(plans, "_resolve_cloud_run_environment", environment)
    execute = AsyncMock()
    monkeypatch.setattr(plans, "_execute_approved_plan", execute)
    body = plans.ApprovePlanAndStartRequest(
        conversation_id=conversation.id,
        project_id=conversation.project_id,
        plan_version_id=plan.id,
        expected_plan_version=1,
        permission_profile="read_only",
        message="Execute reviewed read-only plan",
        message_id="approval-request-message",
        idempotency_key="approval-request-key",
        environment={"kind": "local"},
    )
    return body, execute, environment


@pytest.mark.unit
@pytest.mark.parametrize("policy_permission", ["workspace_write", "full_access"])
async def test_approval_cannot_grant_more_than_explicit_read_only_request(
    monkeypatch,
    test_db,
    test_user,
    test_project_db,
    policy_permission,
):
    body, execute, _ = await _approval_fixture(
        monkeypatch,
        test_db,
        test_user,
        test_project_db,
        policy_permission,
    )
    result = await plans.approve_plan_and_start(body, SimpleNamespace(), test_user, test_db)
    await asyncio.sleep(0)
    canonical = await test_db.get(AgentRunAuthorityModel, result["run"]["id"])
    assert canonical.permission_profile == "read_only"
    assert canonical.authorization_snapshot["permission_profile"] == "read_only"
    execute.assert_awaited_once()


@pytest.mark.unit
@pytest.mark.parametrize(
    "changed",
    [
        {"permission_profile": "full_access"},
        {"environment": {"kind": "worktree"}},
        {"expected_plan_version": 2},
    ],
)
async def test_approval_same_key_rejects_changed_authority_parameters(
    monkeypatch,
    test_db,
    test_user,
    test_project_db,
    changed,
):
    body, execute, environment = await _approval_fixture(
        monkeypatch,
        test_db,
        test_user,
        test_project_db,
        "read_only",
    )
    first = await plans.approve_plan_and_start(body, SimpleNamespace(), test_user, test_db)
    await asyncio.sleep(0)
    changed_body = plans.ApprovePlanAndStartRequest.model_validate(body.model_dump() | changed)
    with pytest.raises(HTTPException) as error:
        await plans.approve_plan_and_start(changed_body, SimpleNamespace(), test_user, test_db)
    assert error.value.status_code == 409
    replay = await plans.approve_plan_and_start(body, SimpleNamespace(), test_user, test_db)
    assert replay["created"] is False
    assert replay["run"]["id"] == first["run"]["id"]
    execute.assert_awaited_once()
    environment.assert_awaited_once()


@pytest.mark.unit
@pytest.mark.parametrize(
    "policy_permission,requested,allowed",
    [
        ("read_only", "read_only", True),
        ("read_only", "workspace_write", False),
        ("read_only", "full_access", False),
        ("workspace_write", "read_only", True),
        ("workspace_write", "workspace_write", True),
        ("workspace_write", "full_access", False),
        ("full_access", "read_only", True),
        ("full_access", "workspace_write", True),
        ("full_access", "full_access", True),
    ],
)
async def test_approval_permission_request_matrix(
    monkeypatch,
    test_db,
    test_user,
    test_project_db,
    policy_permission,
    requested,
    allowed,
):
    body, execute, environment = await _approval_fixture(
        monkeypatch,
        test_db,
        test_user,
        test_project_db,
        policy_permission,
    )
    body = body.model_copy(update={"permission_profile": requested})
    if not allowed:
        with pytest.raises(HTTPException) as error:
            await plans.approve_plan_and_start(body, SimpleNamespace(), test_user, test_db)
        assert error.value.status_code == 403
        assert (await test_db.get(AgentPlanVersionModel, body.plan_version_id)).status == "draft"
        execute.assert_not_awaited()
        environment.assert_not_awaited()
        return
    result = await plans.approve_plan_and_start(body, SimpleNamespace(), test_user, test_db)
    await asyncio.sleep(0)
    run = await test_db.get(AgentRunAuthorityModel, result["run"]["id"])
    assert run.permission_profile == requested
    assert run.authorization_snapshot["approval_request"]["request"] == body.model_dump(mode="json")
    execute.assert_awaited_once()


@pytest.mark.unit
async def test_approval_legacy_receipt_without_original_request_fails_closed(
    monkeypatch,
    test_db,
    test_user,
    test_project_db,
):
    body, execute, environment = await _approval_fixture(
        monkeypatch,
        test_db,
        test_user,
        test_project_db,
        "full_access",
    )
    first = await plans.approve_plan_and_start(body, SimpleNamespace(), test_user, test_db)
    await asyncio.sleep(0)
    run = await test_db.get(AgentPlanRunModel, first["run"]["id"])
    snapshot = dict(run.authorization_snapshot)
    snapshot.pop("approval_request")
    run.authorization_snapshot = snapshot
    await test_db.commit()
    with pytest.raises(HTTPException) as error:
        await plans.approve_plan_and_start(body, SimpleNamespace(), test_user, test_db)
    assert error.value.status_code == 409
    assert error.value.detail["code"] == "PLAN_APPROVAL_RECEIPT_UNVERIFIABLE"
    assert error.value.detail["run_id"] == run.id
    assert run.status == "queued"
    execute.assert_awaited_once()
    environment.assert_awaited_once()


@pytest.mark.unit
async def test_exact_approval_replay_survives_restart_and_stricter_policy_without_execution(
    monkeypatch,
    test_db,
    test_user,
    test_project_db,
):
    body, execute, environment = await _approval_fixture(
        monkeypatch,
        test_db,
        test_user,
        test_project_db,
        "full_access",
    )
    body = body.model_copy(update={"permission_profile": "full_access"})
    first = await plans.approve_plan_and_start(body, SimpleNamespace(), test_user, test_db)
    await asyncio.sleep(0)
    test_db.expunge_all()
    # Replays inspect a durable receipt; they do not authorize or start another execution.
    policy = AsyncMock(return_value=({"revision": 2, "permission_mode": "ask"}, "read_only"))
    monkeypatch.setattr(plans, "_load_workspace_policy_snapshot", policy)
    replay = await plans.approve_plan_and_start(body, SimpleNamespace(), test_user, test_db)
    assert replay["created"] is False
    assert replay["run"]["id"] == first["run"]["id"]
    assert replay["run"]["permission_profile"] == "full_access"
    policy.assert_not_awaited()
    execute.assert_awaited_once()
    environment.assert_awaited_once()
