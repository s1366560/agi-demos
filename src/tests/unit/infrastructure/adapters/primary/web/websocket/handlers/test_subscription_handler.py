"""Unit tests for websocket subscribe handler recovery bridge behavior."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, call

import pytest

from src.infrastructure.adapters.primary.web.websocket.handlers.subscription_handler import (
    SubscribeHandler,
)


def _build_context() -> SimpleNamespace:
    connection_manager = SimpleNamespace(
        subscribe=AsyncMock(),
        try_start_bridge_task=AsyncMock(return_value=True),
        bridge_tasks={},
    )
    conversation_repo = SimpleNamespace(find_by_id=AsyncMock())
    event_repo = SimpleNamespace(
        get_last_event_time=AsyncMock(return_value=(0, 0)),
        get_events_by_message=AsyncMock(
            return_value=[
                SimpleNamespace(
                    conversation_id="conv-1",
                    event_type="observe",
                    event_time_us=100,
                    event_counter=1,
                )
            ]
        ),
    )
    redis_client = SimpleNamespace(get=AsyncMock(return_value=None))
    container = SimpleNamespace(
        conversation_repository=lambda: conversation_repo,
        agent_execution_event_repository=lambda: event_repo,
        redis=lambda: redis_client,
        agent_service=lambda _llm: AsyncMock(),
    )

    context = SimpleNamespace(
        user_id="user-1",
        tenant_id="tenant-1",
        session_id="session-1",
        connection_manager=connection_manager,
        get_scoped_container=lambda: container,
        send_ack=AsyncMock(),
        send_error=AsyncMock(),
    )

    @asynccontextmanager
    async def _fresh_db_context():
        yield context

    context.fresh_db_context = _fresh_db_context
    return context


@pytest.mark.unit
@pytest.mark.asyncio
async def test_subscribe_starts_recovery_bridge_when_running(monkeypatch) -> None:
    context = _build_context()
    handler = SubscribeHandler()
    conversation = SimpleNamespace(user_id="user-1")
    context.get_scoped_container().conversation_repository().find_by_id.return_value = conversation
    context.get_scoped_container().redis().get.return_value = b"msg-1"

    created_tasks = []

    def _fake_create_task(coro):
        coro.close()
        task = SimpleNamespace(done=lambda: False)
        created_tasks.append(task)
        return task

    async def _fake_create_llm_client(_tenant_id: str):
        return AsyncMock()

    monkeypatch.setattr(
        "src.infrastructure.adapters.primary.web.websocket.handlers.subscription_handler.asyncio.create_task",
        _fake_create_task,
    )
    monkeypatch.setattr(
        "src.configuration.factories.create_llm_client",
        _fake_create_llm_client,
    )

    async def _try_start_bridge_task(
        *,
        session_id: str,
        conversation_id: str,
        bridge_message_id: str | None = None,
        task_factory,
    ) -> bool:
        assert session_id == "session-1"
        assert conversation_id == "conv-1"
        assert bridge_message_id == "msg-1"
        task_factory()
        return True

    context.connection_manager.try_start_bridge_task.side_effect = _try_start_bridge_task

    await handler.handle(
        context, {"conversation_id": "conv-1", "from_time_us": 100, "from_counter": 2}
    )

    context.connection_manager.subscribe.assert_awaited_once_with("session-1", "conv-1")
    context.connection_manager.try_start_bridge_task.assert_awaited_once()
    context.send_ack.assert_awaited_once_with("subscribe", conversation_id="conv-1")
    context.send_error.assert_not_awaited()
    assert len(created_tasks) == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_subscribe_keeps_client_recovery_cursor(monkeypatch) -> None:
    context = _build_context()
    handler = SubscribeHandler()
    conversation = SimpleNamespace(user_id="user-1")
    context.get_scoped_container().conversation_repository().find_by_id.return_value = conversation
    context.get_scoped_container().redis().get.return_value = b"msg-1"
    context.get_scoped_container().agent_execution_event_repository().get_events_by_message.return_value = [
        SimpleNamespace(
            conversation_id="conv-1",
            event_type="text_delta",
            event_time_us=320,
            event_counter=7,
        ),
        # Higher watermark from another conversation/message should be ignored
        SimpleNamespace(
            conversation_id="conv-other",
            event_type="text_delta",
            event_time_us=999,
            event_counter=1,
        ),
    ]

    real_create_task = asyncio.create_task
    created_tasks: list[asyncio.Task[None]] = []

    def _fake_create_task(coro):
        task = real_create_task(coro)
        created_tasks.append(task)
        return task

    async def _fake_create_llm_client(_tenant_id: str):
        return AsyncMock()

    stream_mock = AsyncMock()
    monkeypatch.setattr(
        "src.infrastructure.adapters.primary.web.websocket.handlers.subscription_handler.asyncio.create_task",
        _fake_create_task,
    )
    monkeypatch.setattr(
        "src.configuration.factories.create_llm_client",
        _fake_create_llm_client,
    )
    monkeypatch.setattr(
        "src.infrastructure.adapters.primary.web.websocket.handlers.subscription_handler.stream_hitl_response_to_websocket",
        stream_mock,
    )

    async def _try_start_bridge_task(
        *,
        session_id: str,
        conversation_id: str,
        bridge_message_id: str | None = None,
        task_factory,
    ) -> bool:
        assert session_id == "session-1"
        assert conversation_id == "conv-1"
        assert bridge_message_id == "msg-1"
        task_factory()
        return True

    context.connection_manager.try_start_bridge_task.side_effect = _try_start_bridge_task

    await handler.handle(
        context, {"conversation_id": "conv-1", "from_time_us": 100, "from_counter": 1}
    )
    if created_tasks:
        await asyncio.gather(*created_tasks)

    stream_kwargs = stream_mock.call_args.kwargs
    assert stream_kwargs["from_time_us"] == 100
    assert stream_kwargs["from_counter"] == 1
    context.get_scoped_container().agent_execution_event_repository().get_events_by_message.assert_awaited_once_with(
        "conv-1", "msg-1"
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_subscribe_uses_message_scoped_recovery_cursor_when_client_cursor_missing(
    monkeypatch,
) -> None:
    context = _build_context()
    handler = SubscribeHandler()
    conversation = SimpleNamespace(user_id="user-1")
    context.get_scoped_container().conversation_repository().find_by_id.return_value = conversation
    context.get_scoped_container().redis().get.return_value = b"msg-1"
    context.get_scoped_container().agent_execution_event_repository().get_events_by_message.return_value = [
        SimpleNamespace(
            conversation_id="conv-1",
            event_type="text_delta",
            event_time_us=320,
            event_counter=7,
        )
    ]

    real_create_task = asyncio.create_task
    created_tasks: list[asyncio.Task[None]] = []

    def _fake_create_task(coro):
        task = real_create_task(coro)
        created_tasks.append(task)
        return task

    async def _fake_create_llm_client(_tenant_id: str):
        return AsyncMock()

    stream_mock = AsyncMock()
    monkeypatch.setattr(
        "src.infrastructure.adapters.primary.web.websocket.handlers.subscription_handler.asyncio.create_task",
        _fake_create_task,
    )
    monkeypatch.setattr(
        "src.configuration.factories.create_llm_client",
        _fake_create_llm_client,
    )
    monkeypatch.setattr(
        "src.infrastructure.adapters.primary.web.websocket.handlers.subscription_handler.stream_hitl_response_to_websocket",
        stream_mock,
    )

    async def _try_start_bridge_task(
        *,
        session_id: str,
        conversation_id: str,
        bridge_message_id: str | None = None,
        task_factory,
    ) -> bool:
        assert session_id == "session-1"
        assert conversation_id == "conv-1"
        assert bridge_message_id == "msg-1"
        task_factory()
        return True

    context.connection_manager.try_start_bridge_task.side_effect = _try_start_bridge_task

    await handler.handle(context, {"conversation_id": "conv-1"})
    if created_tasks:
        await asyncio.gather(*created_tasks)

    stream_kwargs = stream_mock.call_args.kwargs
    assert stream_kwargs["from_time_us"] == 320
    assert stream_kwargs["from_counter"] == 7
    context.get_scoped_container().agent_execution_event_repository().get_events_by_message.assert_has_awaits(
        [call("conv-1", "msg-1"), call("conv-1", "msg-1")]
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_subscribe_skips_recovery_when_running_key_is_stale() -> None:
    context = _build_context()
    handler = SubscribeHandler()
    conversation = SimpleNamespace(user_id="user-1")
    context.get_scoped_container().conversation_repository().find_by_id.return_value = conversation
    context.get_scoped_container().redis().get.return_value = b"msg-1"
    context.get_scoped_container().agent_execution_event_repository().get_events_by_message.return_value = [
        SimpleNamespace(conversation_id="conv-1", event_type="complete")
    ]

    await handler.handle(context, {"conversation_id": "conv-1"})

    context.connection_manager.subscribe.assert_awaited_once_with("session-1", "conv-1")
    context.connection_manager.try_start_bridge_task.assert_not_awaited()
    context.send_ack.assert_awaited_once_with("subscribe", conversation_id="conv-1")
    context.send_error.assert_not_awaited()
    context.get_scoped_container().agent_execution_event_repository().get_events_by_message.assert_awaited_once_with(
        "conv-1", "msg-1"
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_subscribe_skips_recovery_when_running_key_has_no_persisted_events() -> None:
    context = _build_context()
    handler = SubscribeHandler()
    conversation = SimpleNamespace(user_id="user-1")
    context.get_scoped_container().conversation_repository().find_by_id.return_value = conversation
    context.get_scoped_container().redis().get.return_value = b"attempt-1"
    context.get_scoped_container().agent_execution_event_repository().get_events_by_message.return_value = []

    await handler.handle(context, {"conversation_id": "conv-1"})

    context.connection_manager.subscribe.assert_awaited_once_with("session-1", "conv-1")
    context.connection_manager.try_start_bridge_task.assert_not_awaited()
    context.send_ack.assert_awaited_once_with("subscribe", conversation_id="conv-1")
    context.send_error.assert_not_awaited()
    context.get_scoped_container().agent_execution_event_repository().get_events_by_message.assert_awaited_once_with(
        "conv-1", "attempt-1"
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_subscribe_ignores_boolean_cursor_values(monkeypatch) -> None:
    context = _build_context()
    handler = SubscribeHandler()
    conversation = SimpleNamespace(user_id="user-1")
    context.get_scoped_container().conversation_repository().find_by_id.return_value = conversation
    context.get_scoped_container().redis().get.return_value = b"msg-1"

    real_create_task = asyncio.create_task
    created_tasks: list[asyncio.Task[None]] = []

    def _fake_create_task(coro):
        task = real_create_task(coro)
        created_tasks.append(task)
        return task

    async def _fake_create_llm_client(_tenant_id: str):
        return AsyncMock()

    stream_mock = AsyncMock()
    monkeypatch.setattr(
        "src.infrastructure.adapters.primary.web.websocket.handlers.subscription_handler.asyncio.create_task",
        _fake_create_task,
    )
    monkeypatch.setattr(
        "src.configuration.factories.create_llm_client",
        _fake_create_llm_client,
    )
    monkeypatch.setattr(
        "src.infrastructure.adapters.primary.web.websocket.handlers.subscription_handler.stream_hitl_response_to_websocket",
        stream_mock,
    )

    async def _try_start_bridge_task(
        *,
        session_id: str,
        conversation_id: str,
        bridge_message_id: str | None = None,
        task_factory,
    ) -> bool:
        assert session_id == "session-1"
        assert conversation_id == "conv-1"
        assert bridge_message_id == "msg-1"
        task_factory()
        return True

    context.connection_manager.try_start_bridge_task.side_effect = _try_start_bridge_task

    await handler.handle(
        context,
        {"conversation_id": "conv-1", "from_time_us": True, "from_counter": False},
    )
    if created_tasks:
        await asyncio.gather(*created_tasks)

    context.connection_manager.subscribe.assert_awaited_once_with("session-1", "conv-1")
    context.connection_manager.try_start_bridge_task.assert_awaited_once()
    context.send_ack.assert_awaited_once_with("subscribe", conversation_id="conv-1")
    context.send_error.assert_not_awaited()
    assert len(created_tasks) == 1
    stream_kwargs = stream_mock.call_args.kwargs
    assert stream_kwargs["from_time_us"] == 100
    assert stream_kwargs["from_counter"] == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_subscribe_skips_recovery_when_bridge_already_active() -> None:
    context = _build_context()
    handler = SubscribeHandler()
    conversation = SimpleNamespace(user_id="user-1")
    context.get_scoped_container().conversation_repository().find_by_id.return_value = conversation
    context.get_scoped_container().redis().get.return_value = b"msg-1"
    context.connection_manager.try_start_bridge_task.return_value = False

    await handler.handle(context, {"conversation_id": "conv-1"})

    context.connection_manager.subscribe.assert_awaited_once_with("session-1", "conv-1")
    context.connection_manager.try_start_bridge_task.assert_awaited_once()
    context.send_ack.assert_awaited_once_with("subscribe", conversation_id="conv-1")
    context.send_error.assert_not_awaited()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_subscribe_does_not_init_llm_when_bridge_not_started(monkeypatch) -> None:
    context = _build_context()
    handler = SubscribeHandler()
    conversation = SimpleNamespace(user_id="user-1")
    context.get_scoped_container().conversation_repository().find_by_id.return_value = conversation
    context.get_scoped_container().redis().get.return_value = b"msg-1"
    context.connection_manager.try_start_bridge_task.return_value = False

    create_llm_mock = AsyncMock()
    monkeypatch.setattr(
        "src.configuration.factories.create_llm_client",
        create_llm_mock,
    )

    await handler.handle(context, {"conversation_id": "conv-1"})

    context.connection_manager.subscribe.assert_awaited_once_with("session-1", "conv-1")
    context.connection_manager.try_start_bridge_task.assert_awaited_once()
    create_llm_mock.assert_not_awaited()
    context.send_ack.assert_awaited_once_with("subscribe", conversation_id="conv-1")
    context.send_error.assert_not_awaited()
