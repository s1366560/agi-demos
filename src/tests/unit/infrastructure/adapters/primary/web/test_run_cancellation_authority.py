"""Run cancellation admits only exact versions and retains a durable retry receipt."""

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from sqlalchemy import delete

from src.infrastructure.adapters.primary.web.routers.agent import run_cancellation_authority as api
from src.infrastructure.adapters.secondary.persistence.models import (
    Conversation,
    Project,
    Tenant,
    User,
    UserProject,
    UserTenant,
)
from src.infrastructure.adapters.secondary.persistence.sql_agent_run_authority import (
    ensure_chat_run_authority,
)

pytestmark = pytest.mark.unit


@pytest.fixture
async def cancel_fixture(db_session, monkeypatch):
    user = User(id="u", email="run-cancel@test.invalid", hashed_password="unused")
    db_session.add(user)
    await db_session.flush()
    db_session.add(Tenant(id="t", name="Tenant", slug="cancel-test", owner_id="u"))
    await db_session.flush()
    db_session.add(Project(id="p", tenant_id="t", owner_id="u", name="Project"))
    await db_session.flush()
    conversation = Conversation(id="c", tenant_id="t", project_id="p", user_id="u", title="Session")
    db_session.add_all(
        [
            conversation,
            UserTenant(id="ut", user_id="u", tenant_id="t"),
            UserProject(id="up", user_id="u", project_id="p"),
        ]
    )
    await db_session.commit()
    run = await ensure_chat_run_authority(
        db_session,
        conversation=conversation,
        run_id="r",
        request_message="hello",
        client_message_id=None,
        app_model_context=None,
    )
    store = AsyncMock()
    store.set.return_value = True
    monkeypatch.setattr(api, "current_agent_worker_redis_client_v2", lambda: store)

    @asynccontextmanager
    async def pin_operation(**kwargs):
        assert kwargs["tenant_id"] == run.tenant_id
        assert kwargs["project_id"] == run.project_id
        assert kwargs["session_id"] == run.conversation_id
        yield None

    monkeypatch.setattr(api, "pin_agent_turn_operation_v2", pin_operation)
    return db_session, user, run, store


async def test_cancel_pending_receipt_replays_after_delivery_failure_and_terminal(cancel_fixture):
    db, user, run, store = cancel_fixture
    store.set.side_effect = ConnectionError("offline")
    with pytest.raises(HTTPException) as error:
        await api.cancel_run("r", api.CancelRunRequest(expected_revision=1), user, db)
    assert error.value.status_code == 503
    await db.refresh(run)
    receipt = dict(run.authorization_snapshot["cancellation_receipt"])
    assert run.status == "queued"
    store.set.side_effect = None
    result = await api.cancel_run("r", api.CancelRunRequest(expected_revision=1), user, db)
    assert result.status == "cancel_requested"
    assert result.run.status == "queued"
    assert run.authorization_snapshot["cancellation_receipt"] == receipt
    assert store.set.await_args.args[0] == "agent:run-cancellation:r"
    run.status = "cancelled"
    run.revision = 2
    await db.commit()
    store.set.reset_mock()
    result = await api.cancel_run("r", api.CancelRunRequest(expected_revision=1), user, db)
    assert result.status == "cancelled"
    assert result.run.revision == 2
    store.set.assert_not_awaited()


@pytest.mark.parametrize(
    "status,revision", [("running", 2), ("completed", 1), ("failed", 1), ("cancelled", 1)]
)
async def test_cancel_rejects_stale_or_unrelated_terminal(cancel_fixture, status, revision):
    db, user, run, store = cancel_fixture
    run.status = status
    run.revision = revision
    await db.commit()
    with pytest.raises(HTTPException) as error:
        await api.cancel_run("r", api.CancelRunRequest(expected_revision=1), user, db)
    assert error.value.status_code == 409
    store.set.assert_not_awaited()


@pytest.mark.parametrize(
    "scope", ["tenant", "project", "owner", "tenant_membership", "project_membership"]
)
async def test_cancel_rejects_scope_or_membership_mismatch(cancel_fixture, scope):
    db, user, run, store = cancel_fixture
    if scope == "tenant":
        run.tenant_id = "other"
    elif scope == "project":
        run.project_id = "other"
    elif scope == "owner":
        user = User(id="other", email="other@test.invalid", hashed_password="unused")
    elif scope == "tenant_membership":
        await db.execute(delete(UserTenant))
    else:
        await db.execute(delete(UserProject))
    await db.commit()
    with pytest.raises(HTTPException) as error:
        await api.cancel_run("r", api.CancelRunRequest(expected_revision=1), user, db)
    assert error.value.status_code == 403
    store.set.assert_not_awaited()


async def test_http_contract_serializes_request_ack_and_rejects_boolean_revision(cancel_fixture):
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    db, user, _run, store = cancel_fixture
    app = FastAPI()
    app.include_router(api.router, prefix="/api/v1/agent")
    app.dependency_overrides[api.get_current_user] = lambda: user
    app.dependency_overrides[api.get_db] = lambda: db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/v1/agent/runs/r/cancel", json={"expected_revision": 1})
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "cancel_requested"
        assert body["run"]["status"] == "queued"
        assert body["run"]["revision"] == 1
        assert body["run"]["last_heartbeat_at"] is None
        store.set.reset_mock()
        response = await client.post(
            "/api/v1/agent/runs/r/cancel", json={"expected_revision": True}
        )
        assert response.status_code == 422
        store.set.assert_not_awaited()
