"""Disconnect before a chat worker starts must not leave the authority queued."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from src.domain.model.agent import AgentClientTurnStatus
from src.infrastructure.adapters.primary.web.websocket.handlers import (
    chat_handler,
    subscription_handler,
)
from src.infrastructure.adapters.primary.web.websocket.handlers.chat_handler import (
    _ClientTurnAdmission,
)
from src.infrastructure.adapters.secondary.persistence.models import (
    AgentRunAuthorityModel,
    Conversation,
)
from src.infrastructure.adapters.secondary.persistence.sql_agent_run_authority import (
    fail_unstarted_chat_authority,
)


def _authority(
    *,
    run_id: str,
    conversation_id: str,
    tenant_id: str,
    project_id: str,
    status: str = "queued",
    started_at: datetime | None = None,
) -> AgentRunAuthorityModel:
    now = datetime.now(UTC)
    return AgentRunAuthorityModel(
        id=run_id,
        tenant_id=tenant_id,
        project_id=project_id,
        conversation_id=conversation_id,
        run_kind="chat",
        idempotency_key=f"execution:{run_id}",
        message_id=run_id,
        request_message="hello",
        status=status,
        revision=1,
        permission_profile="read_only",
        authorization_snapshot={},
        created_at=now,
        updated_at=now,
        started_at=started_at,
    )


@pytest.mark.unit
async def test_disconnect_before_start_fails_queued_authority_once(
    test_db, test_user, test_project_db
) -> None:
    conversation = Conversation(
        id="conv-disconnect",
        tenant_id=test_project_db.tenant_id,
        project_id=test_project_db.id,
        user_id=test_user.id,
        title="project session",
    )
    test_db.add(conversation)
    test_db.add(
        _authority(
            run_id="run-unstarted",
            conversation_id=conversation.id,
            tenant_id=conversation.tenant_id,
            project_id=conversation.project_id,
        )
    )
    await test_db.commit()

    closed = await fail_unstarted_chat_authority(
        test_db,
        run_id="run-unstarted",
        tenant_id=conversation.tenant_id,
        project_id=conversation.project_id,
        conversation_id=conversation.id,
        cause="client_disconnected_before_start",
    )
    again = await fail_unstarted_chat_authority(
        test_db,
        run_id="run-unstarted",
        tenant_id=conversation.tenant_id,
        project_id=conversation.project_id,
        conversation_id=conversation.id,
        cause="client_disconnected_before_start",
    )

    row = await test_db.get(AgentRunAuthorityModel, "run-unstarted")
    assert closed is True and again is False
    assert row is not None
    assert row.status == "failed"
    assert row.started_at is None
    assert row.error == "client_disconnected_before_start"


@pytest.mark.unit
async def test_disconnect_does_not_fail_a_running_worker(
    test_db, test_user, test_project_db
) -> None:
    conversation = Conversation(
        id="conv-running",
        tenant_id=test_project_db.tenant_id,
        project_id=test_project_db.id,
        user_id=test_user.id,
        title="project session",
    )
    started = datetime.now(UTC)
    test_db.add(conversation)
    test_db.add(
        _authority(
            run_id="run-running",
            conversation_id=conversation.id,
            tenant_id=conversation.tenant_id,
            project_id=conversation.project_id,
            status="running",
            started_at=started,
        )
    )
    await test_db.commit()

    closed = await fail_unstarted_chat_authority(
        test_db,
        run_id="run-running",
        tenant_id=conversation.tenant_id,
        project_id=conversation.project_id,
        conversation_id=conversation.id,
        cause="client_disconnected_before_start",
    )
    row = await test_db.get(AgentRunAuthorityModel, "run-running")
    assert closed is False
    assert row is not None
    assert row.status == "running"
    assert row.started_at is not None


@pytest.mark.unit
async def test_ack_disconnect_before_model_closes_the_turn_and_does_not_restart(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    closed: dict[str, Any] = {}
    models = {"calls": 0}
    entered = asyncio.Event()

    async def _close(**kwargs: object) -> None:
        closed.update(kwargs)

    async def _wait_for_worker(**_kwargs: object) -> None:
        models["calls"] += 1
        entered.set()
        await asyncio.Event().wait()

    @asynccontextmanager
    async def _pin(*_args: object, **_kwargs: object) -> Any:
        yield object()

    monkeypatch.setattr(
        chat_handler, "acquire_scoped_chat_turn_v2", AsyncMock(return_value=object())
    )
    monkeypatch.setattr(chat_handler, "pin_scoped_agent_turn_operation_v2", _pin)
    monkeypatch.setattr(chat_handler, "_stream_agent_to_websocket_pinned", _wait_for_worker)
    monkeypatch.setattr(chat_handler, "_close_unstarted_turn_after_disconnect", _close)
    context = SimpleNamespace(
        tenant_id="tenant-1",
        user_id="user-1",
        db=object(),
        connection_manager=SimpleNamespace(
            send_to_session=AsyncMock(),
            broadcast_to_conversation=AsyncMock(),
        ),
    )

    task = asyncio.create_task(
        chat_handler.stream_agent_to_websocket(
            context=context,  # type: ignore[arg-type]
            conversation_id="conv-1",
            user_message="hello",
            project_id="project-1",
            execution_message_id="run-1",
        )
    )
    await entered.wait()
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)

    assert models["calls"] == 1
    assert closed == {
        "tenant_id": "tenant-1",
        "project_id": "project-1",
        "conversation_id": "conv-1",
        "run_id": "run-1",
    }
    admission = _ClientTurnAdmission(
        payload_hash="same",
        turn=SimpleNamespace(status=AgentClientTurnStatus.STARTED),  # type: ignore[arg-type]
    )
    assert admission.should_start is False


@pytest.mark.unit
async def test_project_session_without_started_run_skips_recovery_restore(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _no_durable(*_args: object, **_kwargs: object) -> bool:
        return False

    acquire = AsyncMock(side_effect=AssertionError("restore must not run"))
    monkeypatch.setattr(subscription_handler, "_session_has_durable_chat_run", _no_durable)
    monkeypatch.setattr(subscription_handler, "acquire_existing_scoped_session_v2", acquire)

    await subscription_handler._maybe_start_recovery_bridge(
        SimpleNamespace(tenant_id="tenant-1"),  # type: ignore[arg-type]
        "conv-1",
        "project-1",
        {},
    )

    acquire.assert_not_awaited()
