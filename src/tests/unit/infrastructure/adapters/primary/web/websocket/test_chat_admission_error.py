from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.infrastructure.adapters.primary.web.routers.agent.messages import _build_timeline
from src.infrastructure.adapters.primary.web.websocket import chat_admission_error
from src.infrastructure.adapters.primary.web.websocket.handlers import chat_handler
from src.infrastructure.adapters.secondary.persistence.models import (
    Conversation,
    Project,
    Tenant,
    User,
    UserProject,
    UserTenant,
)
from src.infrastructure.adapters.secondary.persistence.sql_agent_execution_event_repository import (
    SqlAgentExecutionEventRepository,
)


@pytest.mark.unit
@pytest.mark.parametrize("authorized", [True, False])
async def test_admission_failure_is_replayable_only_in_authorized_scope(
    db_session, monkeypatch, authorized
):
    db_session.add(User(id="u", email="admission-error@test.invalid", hashed_password="unused"))
    await db_session.flush()
    db_session.add(Tenant(id="t", name="Tenant", slug="error-history", owner_id="u"))
    await db_session.flush()
    db_session.add(Project(id="p", tenant_id="t", owner_id="u", name="Project"))
    await db_session.flush()
    db_session.add_all(
        [
            Conversation(id="c", tenant_id="t", project_id="p", user_id="u", title="Session"),
            UserTenant(id="ut", user_id="u", tenant_id="t"),
            UserProject(id="up", user_id="u", project_id="p"),
        ]
    )
    await db_session.commit()

    @asynccontextmanager
    async def factory():
        yield db_session

    monkeypatch.setattr(chat_admission_error, "async_session_factory", factory)
    data = await chat_admission_error.persist_chat_admission_error(
        user_id="u",
        tenant_id="t" if authorized else "other",
        project_id="p",
        conversation_id="c",
        message_id="turn-1",
        data={"message": "Bundle differs", "code": "bundle_mismatch"},
    )
    events = await SqlAgentExecutionEventRepository(db_session).get_events_by_message_ids(
        "c", {"turn-1"}
    )
    persisted = events.get("turn-1", [])
    if not authorized:
        assert persisted == []
        return
    timeline = _build_timeline(persisted, {}, {}, {}, {}, {}, {})
    assert len(timeline) == 1
    assert timeline[0]["type"] == "error"
    assert timeline[0]["message"] == "Bundle differs"
    assert timeline[0]["eventTimeUs"] == data["event_time_us"]


@pytest.mark.unit
async def test_admission_error_does_not_commit_caller_turn_claim(monkeypatch):
    manager = SimpleNamespace(send_to_session=AsyncMock())
    context = SimpleNamespace(
        user_id="u", tenant_id="t", session_id="ws", db=AsyncMock(), connection_manager=manager
    )
    monkeypatch.setattr(
        chat_handler,
        "acquire_scoped_chat_turn_v2",
        AsyncMock(side_effect=RuntimeError("admission failed")),
    )
    persist = AsyncMock(
        return_value={"message": "admission failed", "event_time_us": 1234, "event_counter": 0}
    )
    monkeypatch.setattr(chat_admission_error, "persist_chat_admission_error", persist)
    await chat_handler.stream_agent_to_websocket(
        context, "c", "hello", "p", execution_message_id="turn-1"
    )
    persist.assert_awaited_once()
    context.db.commit.assert_not_awaited()
    assert manager.send_to_session.await_args.args[1]["data"]["event_time_us"] == 1234
