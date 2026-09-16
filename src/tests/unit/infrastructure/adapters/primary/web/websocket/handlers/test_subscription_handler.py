"""Unit tests for websocket subscribe handler recovery bridge behavior."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.infrastructure.adapters.primary.web.websocket.handlers import subscription_handler
from src.infrastructure.adapters.primary.web.websocket.handlers.subscription_handler import (
    SubscribeHandler,
)
from src.infrastructure.plugins.v2.session_event_log_types import (
    SessionEventCursorV2,
    SessionMessageRecoveryStateV2,
)


class _FakeRecoveryFork:
    def __init__(self, service: object) -> None:
        self.resolver = SimpleNamespace(resolve=AsyncMock(return_value=service))
        self.admit_calls: list[dict[str, object]] = []
        self.release = AsyncMock()
        self.operation = SimpleNamespace(
            require=self._require,
            context=SimpleNamespace(scope=SimpleNamespace(project_id="project-1")),
        )

    def _require(self, service: str) -> object:
        assert service == "service:agent.recovery-stream"
        return self.resolver

    @asynccontextmanager
    async def admit(self, **kwargs: object):
        self.admit_calls.append(dict(kwargs))
        yield self.operation


def _build_context(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    connection_manager = SimpleNamespace(
        subscribe=AsyncMock(),
        try_start_bridge_task=AsyncMock(return_value=True),
        bridge_tasks={},
    )
    conversation_access = SimpleNamespace(find_by_id=AsyncMock())
    redis_client = SimpleNamespace(get=AsyncMock(return_value=None))
    session_event_log = SimpleNamespace(
        message_recovery_state=AsyncMock(
            return_value=SessionMessageRecoveryStateV2(
                has_events=True,
                is_terminal=False,
                cursor=SessionEventCursorV2(event_time_us=100, event_counter=1),
            )
        ),
    )
    container = SimpleNamespace(
        conversation_repository=MagicMock(
            side_effect=AssertionError("static conversation repository must not be used")
        ),
        agent_execution_event_repository=MagicMock(
            side_effect=AssertionError("static event repository must not be used")
        ),
        redis=MagicMock(side_effect=AssertionError("static Redis must not be used")),
        agent_service=MagicMock(
            side_effect=AssertionError("static AgentService factory must not be used")
        ),
    )

    context = SimpleNamespace(
        user_id="user-1",
        tenant_id="tenant-1",
        session_id="session-1",
        db=SimpleNamespace(),
        connection_manager=connection_manager,
        get_scoped_container=lambda: container,
        send_ack=AsyncMock(),
        send_error=AsyncMock(),
        v2_redis=redis_client,
        v2_session_event_log=session_event_log,
        v2_conversation_access=conversation_access,
    )
    context.v2_authorize = AsyncMock()
    monkeypatch.setattr(
        subscription_handler, "authorize_existing_scoped_session_v2", context.v2_authorize
    )
    context.v2_agent_service = AsyncMock()
    context.v2_recovery_fork = _FakeRecoveryFork(context.v2_agent_service)
    context.v2_recovery_stream = AsyncMock()

    @asynccontextmanager
    async def _fresh_db_context():
        yield context

    context.fresh_db_context = _fresh_db_context

    @asynccontextmanager
    async def _operation_context(_reservation: object, **_kwargs: object):
        yield None

    monkeypatch.setattr(
        subscription_handler, "pin_scoped_agent_turn_operation_v2", _operation_context
    )
    monkeypatch.setattr(
        subscription_handler, "acquire_existing_scoped_session_v2", AsyncMock(return_value=object())
    )
    monkeypatch.setattr(
        subscription_handler,
        "fork_current_agent_operation_v2",
        AsyncMock(return_value=context.v2_recovery_fork),
        raising=False,
    )
    monkeypatch.setattr(
        subscription_handler,
        "current_agent_worker_redis_client_v2",
        lambda: context.v2_redis,
    )
    monkeypatch.setattr(
        subscription_handler,
        "_session_event_log_service_v2",
        lambda: context.v2_session_event_log,
    )
    monkeypatch.setattr(
        subscription_handler,
        "stream_hitl_response_to_websocket",
        context.v2_recovery_stream,
    )

    @asynccontextmanager
    async def _conversation_access_authority(
        _context: object,
        *,
        conversation_id: str,
    ):
        assert conversation_id == "conv-1"
        yield SimpleNamespace(service=context.v2_conversation_access)

    monkeypatch.setattr(
        subscription_handler,
        "conversation_access_application_authority_v2",
        _conversation_access_authority,
        raising=False,
    )
    return context


@pytest.mark.unit
@pytest.mark.asyncio
async def test_subscribe_starts_recovery_bridge_when_running(monkeypatch) -> None:
    context = _build_context(monkeypatch)
    handler = SubscribeHandler()
    conversation = SimpleNamespace(
        user_id="user-1",
        tenant_id="tenant-1",
        project_id="project-1",
    )
    context.v2_conversation_access.find_by_id.return_value = conversation
    context.v2_redis.get.return_value = b"msg-1"

    real_create_task = asyncio.create_task
    created_tasks: list[asyncio.Task[None]] = []

    def _fake_create_task(coro, *, context=None):
        task = real_create_task(coro, context=context)
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
        replace_existing: bool = False,
    ) -> bool:
        assert session_id == "session-1"
        assert conversation_id == "conv-1"
        assert bridge_message_id == "msg-1"
        assert replace_existing is True
        task_factory()
        return True

    context.connection_manager.try_start_bridge_task.side_effect = _try_start_bridge_task

    await handler.handle(
        context, {"conversation_id": "conv-1", "from_time_us": 100, "from_counter": 2}
    )
    await asyncio.gather(*created_tasks)

    context.connection_manager.subscribe.assert_awaited_once_with("session-1", "conv-1")
    context.connection_manager.try_start_bridge_task.assert_awaited_once()
    context.send_ack.assert_awaited_once_with("subscribe", conversation_id="conv-1")
    context.send_error.assert_not_awaited()
    assert len(created_tasks) == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_subscribe_rejects_conversation_from_another_tenant(monkeypatch) -> None:
    context = _build_context(monkeypatch)
    handler = SubscribeHandler()
    context.v2_conversation_access.find_by_id.return_value = SimpleNamespace(
        user_id="user-1",
        tenant_id="tenant-other",
        project_id="project-other",
    )

    await handler.handle(context, {"conversation_id": "conv-1"})

    context.connection_manager.subscribe.assert_not_awaited()
    context.connection_manager.try_start_bridge_task.assert_not_awaited()
    context.send_ack.assert_not_awaited()
    context.send_error.assert_awaited_once_with(
        "You do not have permission to access this conversation",
        conversation_id="conv-1",
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_subscribe_keeps_client_recovery_cursor(monkeypatch) -> None:
    context = _build_context(monkeypatch)
    handler = SubscribeHandler()
    conversation = SimpleNamespace(
        user_id="user-1",
        tenant_id="tenant-1",
        project_id="project-1",
    )
    context.v2_conversation_access.find_by_id.return_value = conversation
    context.v2_redis.get.return_value = b"msg-1"
    context.v2_session_event_log.message_recovery_state.return_value = (
        SessionMessageRecoveryStateV2(
            has_events=True,
            is_terminal=False,
            cursor=SessionEventCursorV2(event_time_us=320, event_counter=7),
        )
    )

    real_create_task = asyncio.create_task
    created_tasks: list[asyncio.Task[None]] = []

    def _fake_create_task(coro, *, context=None):
        task = real_create_task(coro, context=context)
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
        replace_existing: bool = False,
    ) -> bool:
        assert session_id == "session-1"
        assert conversation_id == "conv-1"
        assert bridge_message_id == "msg-1"
        assert replace_existing is True
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
    context.v2_session_event_log.message_recovery_state.assert_awaited_once_with(
        conversation_id="conv-1",
        message_id="msg-1",
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_subscribe_uses_message_scoped_recovery_cursor_when_client_cursor_missing(
    monkeypatch,
) -> None:
    context = _build_context(monkeypatch)
    handler = SubscribeHandler()
    conversation = SimpleNamespace(
        user_id="user-1",
        tenant_id="tenant-1",
        project_id="project-1",
    )
    context.v2_conversation_access.find_by_id.return_value = conversation
    context.v2_redis.get.return_value = b"msg-1"
    context.v2_session_event_log.message_recovery_state.return_value = (
        SessionMessageRecoveryStateV2(
            has_events=True,
            is_terminal=False,
            cursor=SessionEventCursorV2(event_time_us=320, event_counter=7),
        )
    )

    real_create_task = asyncio.create_task
    created_tasks: list[asyncio.Task[None]] = []

    def _fake_create_task(coro, *, context=None):
        task = real_create_task(coro, context=context)
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
    context.v2_session_event_log.message_recovery_state.assert_awaited_once_with(
        conversation_id="conv-1",
        message_id="msg-1",
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_subscribe_skips_recovery_when_running_key_is_stale(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _build_context(monkeypatch)
    handler = SubscribeHandler()
    conversation = SimpleNamespace(
        user_id="user-1",
        tenant_id="tenant-1",
        project_id="project-1",
    )
    context.v2_conversation_access.find_by_id.return_value = conversation
    context.v2_redis.get.return_value = b"msg-1"
    context.v2_session_event_log.message_recovery_state.return_value = (
        SessionMessageRecoveryStateV2(
            has_events=True,
            is_terminal=True,
            cursor=SessionEventCursorV2(event_time_us=100, event_counter=1),
        )
    )

    await handler.handle(context, {"conversation_id": "conv-1"})

    context.connection_manager.subscribe.assert_awaited_once_with("session-1", "conv-1")
    context.connection_manager.try_start_bridge_task.assert_not_awaited()
    context.send_ack.assert_awaited_once_with("subscribe", conversation_id="conv-1")
    context.send_error.assert_not_awaited()
    context.v2_session_event_log.message_recovery_state.assert_awaited_once_with(
        conversation_id="conv-1",
        message_id="msg-1",
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_subscribe_skips_recovery_when_running_key_has_no_persisted_events(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _build_context(monkeypatch)
    handler = SubscribeHandler()
    conversation = SimpleNamespace(
        user_id="user-1",
        tenant_id="tenant-1",
        project_id="project-1",
    )
    context.v2_conversation_access.find_by_id.return_value = conversation
    context.v2_redis.get.return_value = b"attempt-1"
    context.v2_session_event_log.message_recovery_state.return_value = (
        SessionMessageRecoveryStateV2(
            has_events=False,
            is_terminal=False,
        )
    )

    await handler.handle(context, {"conversation_id": "conv-1"})

    context.connection_manager.subscribe.assert_awaited_once_with("session-1", "conv-1")
    context.connection_manager.try_start_bridge_task.assert_not_awaited()
    context.send_ack.assert_awaited_once_with("subscribe", conversation_id="conv-1")
    context.send_error.assert_not_awaited()
    context.v2_session_event_log.message_recovery_state.assert_awaited_once_with(
        conversation_id="conv-1",
        message_id="attempt-1",
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_subscribe_does_not_fallback_when_v2_session_log_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _build_context(monkeypatch)
    handler = SubscribeHandler()
    conversation = SimpleNamespace(
        user_id="user-1",
        tenant_id="tenant-1",
        project_id="project-1",
    )
    context.v2_conversation_access.find_by_id.return_value = conversation
    context.v2_redis.get.return_value = b"msg-1"
    context.v2_session_event_log.message_recovery_state.side_effect = RuntimeError(
        "v2 session log unavailable"
    )

    await handler.handle(context, {"conversation_id": "conv-1"})

    context.connection_manager.subscribe.assert_awaited_once_with("session-1", "conv-1")
    context.connection_manager.try_start_bridge_task.assert_not_awaited()
    context.get_scoped_container().redis.assert_not_called()
    context.get_scoped_container().agent_execution_event_repository.assert_not_called()
    context.send_ack.assert_awaited_once_with("subscribe", conversation_id="conv-1")
    context.send_error.assert_not_awaited()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_subscribe_does_not_fallback_when_v2_conversation_access_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _build_context(monkeypatch)
    handler = SubscribeHandler()

    @asynccontextmanager
    async def _unavailable_authority(
        _context: object,
        *,
        conversation_id: str,
    ):
        raise RuntimeError(f"v2 conversation access unavailable for {conversation_id}")
        yield

    monkeypatch.setattr(
        subscription_handler,
        "conversation_access_application_authority_v2",
        _unavailable_authority,
        raising=False,
    )

    await handler.handle(context, {"conversation_id": "conv-1"})

    context.get_scoped_container().conversation_repository.assert_not_called()
    context.connection_manager.subscribe.assert_not_awaited()
    context.send_ack.assert_not_awaited()
    context.send_error.assert_awaited_once_with(
        "Failed to subscribe (see server logs)",
        conversation_id="conv-1",
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_subscribe_ignores_boolean_cursor_values(monkeypatch) -> None:
    context = _build_context(monkeypatch)
    handler = SubscribeHandler()
    conversation = SimpleNamespace(
        user_id="user-1",
        tenant_id="tenant-1",
        project_id="project-1",
    )
    context.v2_conversation_access.find_by_id.return_value = conversation
    context.v2_redis.get.return_value = b"msg-1"

    real_create_task = asyncio.create_task
    created_tasks: list[asyncio.Task[None]] = []

    def _fake_create_task(coro, *, context=None):
        task = real_create_task(coro, context=context)
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
async def test_subscribe_skips_recovery_when_bridge_already_active(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _build_context(monkeypatch)
    handler = SubscribeHandler()
    conversation = SimpleNamespace(
        user_id="user-1",
        tenant_id="tenant-1",
        project_id="project-1",
    )
    context.v2_conversation_access.find_by_id.return_value = conversation
    context.v2_redis.get.return_value = b"msg-1"
    context.connection_manager.try_start_bridge_task.return_value = False

    await handler.handle(context, {"conversation_id": "conv-1"})

    context.connection_manager.subscribe.assert_awaited_once_with("session-1", "conv-1")
    context.connection_manager.try_start_bridge_task.assert_awaited_once()
    context.send_ack.assert_awaited_once_with("subscribe", conversation_id="conv-1")
    context.send_error.assert_not_awaited()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_subscribe_does_not_init_llm_when_bridge_not_started(monkeypatch) -> None:
    context = _build_context(monkeypatch)
    handler = SubscribeHandler()
    conversation = SimpleNamespace(
        user_id="user-1",
        tenant_id="tenant-1",
        project_id="project-1",
    )
    context.v2_conversation_access.find_by_id.return_value = conversation
    context.v2_redis.get.return_value = b"msg-1"
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


@pytest.mark.unit
@pytest.mark.asyncio
async def test_subscribe_releases_generation_fork_when_bridge_is_not_started(monkeypatch) -> None:
    context = _build_context(monkeypatch)
    context.v2_conversation_access.find_by_id.return_value = SimpleNamespace(
        user_id="user-1",
        tenant_id="tenant-1",
        project_id="project-1",
    )
    context.v2_redis.get.return_value = b"msg-1"
    context.connection_manager.try_start_bridge_task.return_value = False

    await SubscribeHandler().handle(context, {"conversation_id": "conv-1"})

    context.v2_recovery_fork.release.assert_awaited_once_with()
    context.v2_recovery_fork.resolver.resolve.assert_not_awaited()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_subscribe_releases_generation_fork_when_task_is_cancelled_before_start(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _build_context(monkeypatch)
    context.v2_conversation_access.find_by_id.return_value = SimpleNamespace(
        user_id="user-1",
        tenant_id="tenant-1",
        project_id="project-1",
    )
    context.v2_redis.get.return_value = b"msg-1"
    created_tasks: list[asyncio.Task[None]] = []

    async def try_start_bridge_task(**kwargs: object) -> bool:
        task_factory = kwargs["task_factory"]
        assert callable(task_factory)
        task = task_factory()
        assert isinstance(task, asyncio.Task)
        created_tasks.append(task)
        task.cancel()
        return True

    context.connection_manager.try_start_bridge_task.side_effect = try_start_bridge_task

    await SubscribeHandler().handle(context, {"conversation_id": "conv-1"})
    await asyncio.gather(*created_tasks, return_exceptions=True)
    await asyncio.sleep(0)

    context.v2_recovery_fork.release.assert_awaited_once_with()
    assert context.v2_recovery_fork.admit_calls == []


@pytest.mark.unit
def test_subscription_recovery_has_no_static_llm_or_agent_service_factory() -> None:
    source = Path(subscription_handler.__file__).read_text(encoding="utf-8")

    assert "create_llm_client" not in source
    assert "get_scoped_container().agent_service" not in source


async def test_recovery_authorization_revoked_before_stream_releases_fork(monkeypatch):
    context = _build_context(monkeypatch)
    context.v2_conversation_access.find_by_id.return_value = SimpleNamespace(
        user_id="user-1", tenant_id="tenant-1", project_id="project-1"
    )
    context.v2_redis.get.return_value = b"msg-1"
    context.v2_authorize.side_effect = [None, PermissionError("membership revoked")]
    tasks = []

    async def start(**kwargs):
        tasks.append(kwargs["task_factory"]())
        return True

    context.connection_manager.try_start_bridge_task.side_effect = start
    await SubscribeHandler().handle(context, {"conversation_id": "conv-1"})
    results = await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), 2)
    assert len(results) == 1 and isinstance(results[0], PermissionError)
    context.v2_recovery_fork.resolver.resolve.assert_not_awaited()
    context.v2_recovery_stream.assert_not_awaited()
    context.v2_recovery_fork.release.assert_awaited_once_with()


async def test_subscribe_revoked_membership_never_subscribes_or_acknowledges(monkeypatch):
    context = _build_context(monkeypatch)
    context.v2_conversation_access.find_by_id.return_value = SimpleNamespace(
        user_id="user-1", tenant_id="tenant-1", project_id="project-1"
    )
    context.v2_authorize.side_effect = PermissionError("membership revoked")
    await SubscribeHandler().handle(context, {"conversation_id": "conv-1"})
    context.connection_manager.subscribe.assert_not_awaited()
    context.connection_manager.try_start_bridge_task.assert_not_awaited()
    context.send_ack.assert_not_awaited()
    context.send_error.assert_awaited_once()
    context.v2_recovery_fork.resolver.resolve.assert_not_awaited()
