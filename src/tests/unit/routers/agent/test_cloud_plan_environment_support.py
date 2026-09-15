"""A sandbox must not be advertised or admitted as a Git worktree."""

from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from src.infrastructure.adapters.primary.web.routers.agent import plans
from src.infrastructure.adapters.secondary.persistence.models import AgentPlanRunModel
from src.tests.unit.routers.agent.test_plan_approval_request_contract import _approval_fixture


async def test_cloud_worktree_rejected_before_environment_or_queue_side_effects(
    monkeypatch, test_db, test_user, test_project_db
):
    body, execute, environment = await _approval_fixture(
        monkeypatch, test_db, test_user, test_project_db, "full_access"
    )
    body = body.model_copy(
        update={"environment": plans.ApprovePlanEnvironmentRequest(kind="worktree")}
    )
    with pytest.raises(HTTPException) as caught:
        await plans.approve_plan_and_start(body, SimpleNamespace(), test_user, test_db)
    assert caught.value.status_code == 422
    assert caught.value.detail["code"] == "PLAN_ENVIRONMENT_UNSUPPORTED"
    environment.assert_not_awaited()
    execute.assert_not_awaited()
    assert await test_db.scalar(select(AgentPlanRunModel.id)) is None


async def test_verified_historical_worktree_receipt_is_read_only_replay(
    monkeypatch, test_db, test_user, test_project_db
):
    import asyncio

    body, execute, environment = await _approval_fixture(
        monkeypatch, test_db, test_user, test_project_db, "full_access"
    )
    first = await plans.approve_plan_and_start(body, SimpleNamespace(), test_user, test_db)
    await asyncio.sleep(0)
    run = await test_db.get(AgentPlanRunModel, first["run"]["id"])
    historical = plans.ApprovePlanAndStartRequest.model_validate(
        body.model_dump() | {"environment": {"kind": "worktree"}}
    )
    identity = plans.approval_request_identity(
        historical.model_dump(mode="json"),
        tenant_id=test_project_db.tenant_id,
        user_id=test_user.id,
    )
    run.authorization_snapshot = run.authorization_snapshot | {
        "approval_request": identity,
        "environment": {"id": "historical-environment", "kind": "worktree"},
    }
    await test_db.commit()
    replay = await plans.approve_plan_and_start(historical, SimpleNamespace(), test_user, test_db)
    assert replay["created"] is False
    assert replay["run"]["id"] == first["run"]["id"]
    assert replay["run"]["environment"]["kind"] == "worktree"
    environment.assert_awaited_once()
    execute.assert_awaited_once()


async def test_cloud_projection_advertises_only_implemented_environment():
    from src.application.services.conversation_session_projection_service import (
        ConversationSessionProjectionService,
    )
    from src.tests.unit.application.services.test_conversation_session_projection_service import (
        NOW,
        FakeConversationSessionReader,
        snapshot,
    )

    projection = await ConversationSessionProjectionService(
        FakeConversationSessionReader(snapshot())
    ).get_projection(
        conversation_id="conversation-1",
        tenant_id="tenant-1",
        project_id="project-1",
        workspace_id="workspace-1",
        user_id="user-1",
        now=NOW,
    )
    assert projection.model_dump()["capabilities"]["environment_kinds"] == ["local"]
