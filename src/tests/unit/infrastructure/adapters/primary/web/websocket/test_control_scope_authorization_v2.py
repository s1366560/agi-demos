"""Real SQL control scope checks precede runtime admission and dispatch."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import delete, update

from src.infrastructure.adapters.primary.web.websocket.handlers import control_handler
from src.infrastructure.adapters.secondary.persistence.models import (
    Conversation,
    Project,
    Tenant,
    User,
    UserProject,
    UserTenant,
)

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "denied", ["owner", "tenant", "project_ancestry", "tenant_membership", "project_membership"]
)
async def test_invalid_control_scope_never_acquires_or_dispatches(db_session, monkeypatch, denied):
    db_session.add(User(id="u", email="control-scope@test.invalid", hashed_password="unused"))
    await db_session.flush()
    db_session.add_all(
        [
            Tenant(id="t", name="Tenant", slug="control-scope", owner_id="u"),
            Tenant(id="other", name="Other", slug="control-other", owner_id="u"),
        ]
    )
    await db_session.flush()
    db_session.add(Project(id="p", tenant_id="t", owner_id="u", name="Project"))
    await db_session.flush()
    db_session.add_all(
        [
            Conversation(id="s", tenant_id="t", project_id="p", user_id="u", title="Session"),
            UserTenant(id="ut", user_id="u", tenant_id="t"),
            UserProject(id="up", user_id="u", project_id="p"),
        ]
    )
    await db_session.commit()
    context = SimpleNamespace(
        user_id="u",
        tenant_id="t",
        db=db_session,
        send_json=AsyncMock(),
    )
    if denied == "owner":
        context.user_id = "other"
    elif denied == "tenant":
        context.tenant_id = "other"
    elif denied == "project_ancestry":
        await db_session.execute(update(Project).values(tenant_id="other"))
    elif denied == "tenant_membership":
        await db_session.execute(delete(UserTenant))
    else:
        await db_session.execute(delete(UserProject))
    await db_session.commit()
    acquire = AsyncMock()
    dispatch = AsyncMock()
    monkeypatch.setattr(control_handler, "_acquire_control_reservation_v2", acquire)
    monkeypatch.setattr(control_handler.RedisControlChannel, "send_control", dispatch)
    await control_handler.KillRunHandler().handle(
        context,
        {
            "type": "kill_run",
            "conversation_id": "s",
            "run_id": "run",
            "expected_run_revision": 1,
            "idempotency_key": "control-scope-test",
        },
    )
    acquire.assert_not_awaited()
    dispatch.assert_not_awaited()
    assert context.send_json.call_args.args[0]["reason_code"] == "control_scope_denied"
