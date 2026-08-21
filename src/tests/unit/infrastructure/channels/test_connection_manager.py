"""Unit tests for ChannelConnectionManager scheduling behavior."""

import asyncio
import inspect
from concurrent.futures import Future
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from src.domain.model.channels.message import (
    ChatType,
    Message,
    MessageContent,
    MessageType,
    SenderInfo,
)
from src.infrastructure.channels.connection_manager import (
    ChannelConnectionManager,
    ConnectionStatus,
    ManagedConnection,
)
from src.infrastructure.plugins.v2.runtime import RuntimeV2Error


class _FakeGenerationLease:
    def __init__(self, generation: object) -> None:
        self.generation = generation
        self.release_calls = 0

    async def __aenter__(self) -> object:
        return self.generation

    async def release(self) -> None:
        self.release_calls += 1


class _FakeGenerationHost:
    def __init__(self, lease: _FakeGenerationLease) -> None:
        self.lease = lease
        self.acquire_calls = 0

    async def acquire(self) -> _FakeGenerationLease:
        self.acquire_calls += 1
        return self.lease


def _resolver_generation(
    *,
    metadata: object | None,
    build: AsyncMock,
) -> tuple[object, object]:
    resolver = SimpleNamespace(
        metadata=lambda _channel_type: metadata,
        list_metadata=dict,
        build=build,
    )
    generation = SimpleNamespace(resolve=lambda _service, _scope: resolver)
    return generation, resolver


def _build_message() -> Message:
    return Message(
        channel="feishu",
        chat_type=ChatType.P2P,
        chat_id="chat_1",
        sender=SenderInfo(id="ou_sender"),
        content=MessageContent(type=MessageType.TEXT, text="hello"),
    )


@pytest.mark.unit
def test_message_handler_redacts_schedule_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Message handler scheduling failures should not log raw exception text."""
    exception_detail = "schedule failed channel-handler-secret-1357"

    manager = ChannelConnectionManager(message_router=lambda _message: None)
    config = SimpleNamespace(
        id="channel-config-secret-2468",
        project_id="project-1",
        channel_type="feishu",
        rate_limit_per_minute=60,
    )

    def fail_schedule(_message: Message) -> None:
        raise RuntimeError(exception_detail)

    manager._schedule_route_message = fail_schedule  # type: ignore[method-assign]
    handler = manager._build_message_handler(config)  # type: ignore[arg-type]

    with caplog.at_level(
        "ERROR",
        logger="src.infrastructure.channels.connection_manager",
    ):
        handler(_build_message())

    assert "Error routing message" in caplog.text
    assert exception_detail not in caplog.text
    assert "channel-config-secret-2468" not in caplog.text
    assert "error_type=RuntimeError" in caplog.text


@pytest.mark.unit
@pytest.mark.asyncio
async def test_update_db_status_redacts_session_failure(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """DB status update failures should not log raw exception text."""
    exception_detail = "session failed channel-db-secret-8642"

    class _FailingSessionContext:
        @staticmethod
        async def __aenter__() -> object:
            raise RuntimeError(exception_detail)

        @staticmethod
        async def __aexit__(*args: object) -> None:
            return None

    manager = ChannelConnectionManager(session_factory=lambda: _FailingSessionContext())

    with caplog.at_level(
        "WARNING",
        logger="src.infrastructure.channels.connection_manager",
    ):
        await manager._update_db_status("config-secret-1357", "error", "failed")

    assert "Failed to update DB status" in caplog.text
    assert exception_detail not in caplog.text
    assert "config-secret-1357" not in caplog.text
    assert "error_type=RuntimeError" in caplog.text


@pytest.mark.unit
@pytest.mark.asyncio
async def test_cleanup_connection_redacts_disconnect_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Disconnect cleanup failures should not log raw config IDs or exception text."""
    exception_detail = "disconnect failed channel-cleanup-secret-1357"
    secret_config_id = "channel-config-secret-2468"

    class _FailingAdapter:
        @staticmethod
        async def disconnect() -> None:
            raise RuntimeError(exception_detail)

    manager = ChannelConnectionManager()
    connection = ManagedConnection(
        config_id=secret_config_id,
        project_id="project-1",
        channel_type="feishu",
        adapter=_FailingAdapter(),
        status=ConnectionStatus.CONNECTED,
    )
    config = SimpleNamespace(id=secret_config_id)

    with caplog.at_level(
        "WARNING",
        logger="src.infrastructure.channels.connection_manager",
    ):
        await manager._cleanup_connection(connection, config)  # type: ignore[arg-type]

    assert connection.status == ConnectionStatus.DISCONNECTED
    assert "Error disconnecting" in caplog.text
    assert secret_config_id not in caplog.text
    assert exception_detail not in caplog.text
    assert "error_type=RuntimeError" in caplog.text
    assert "has_config_id=True" in caplog.text


@pytest.mark.unit
@pytest.mark.asyncio
async def test_connection_loop_redacts_error_state_and_log(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Connection loop failures should not expose raw exceptions through logs or status."""
    exception_detail = "connect failed channel-loop-secret-1357"
    secret_config_id = "channel-config-secret-2468"
    expected_error = "Connection error: RuntimeError"

    manager = ChannelConnectionManager()
    connection = ManagedConnection(
        config_id=secret_config_id,
        project_id="project-1",
        channel_type="feishu",
        adapter=object(),
        status=ConnectionStatus.DISCONNECTED,
    )
    config = SimpleNamespace(id=secret_config_id)

    async def _fail_attempt(_connection: ManagedConnection, _config: object) -> None:
        raise RuntimeError(exception_detail)

    manager._attempt_connect = _fail_attempt  # type: ignore[method-assign]
    manager._handle_reconnect_backoff = AsyncMock(return_value=True)  # type: ignore[method-assign]
    manager._cleanup_connection = AsyncMock()  # type: ignore[method-assign]
    manager._update_db_status = AsyncMock()  # type: ignore[method-assign]

    with caplog.at_level(
        "ERROR",
        logger="src.infrastructure.channels.connection_manager",
    ):
        await manager._connection_loop(connection, config)  # type: ignore[arg-type]

    assert "Connection error" in caplog.text
    assert exception_detail not in caplog.text
    assert secret_config_id not in caplog.text
    assert "error_type=RuntimeError" in caplog.text
    assert "has_config_id=True" in caplog.text
    assert connection.status == ConnectionStatus.ERROR
    assert connection.last_error == expected_error
    manager._update_db_status.assert_awaited_once_with(  # type: ignore[attr-defined]
        secret_config_id,
        "error",
        expected_error,
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_safe_route_message_redacts_router_exception(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Router failures should not log raw exception text."""
    exception_detail = "router failed channel-router-secret-9753"

    async def _router(_message: Message) -> None:
        raise RuntimeError(exception_detail)

    manager = ChannelConnectionManager(message_router=_router)

    with caplog.at_level(
        "ERROR",
        logger="src.infrastructure.channels.connection_manager",
    ):
        await manager._safe_route_message(_build_message())

    assert "Message routing error" in caplog.text
    assert exception_detail not in caplog.text
    assert "error_type=RuntimeError" in caplog.text


@pytest.mark.unit
def test_schedule_route_message_uses_main_loop() -> None:
    """Routing should always be scheduled onto the manager main loop."""

    async def _router(_message: Message) -> None:
        return None

    class _Loop:
        @staticmethod
        def is_closed() -> bool:
            return False

        @staticmethod
        def is_running() -> bool:
            return True

    manager = ChannelConnectionManager(message_router=_router)
    manager._main_loop = _Loop()  # type: ignore[assignment]
    message = _build_message()

    class _FakeFuture:
        @staticmethod
        def add_done_callback(_cb):
            return None

    captured = {}

    def _fake_run_coroutine_threadsafe(coro, loop):
        captured["loop"] = loop
        coro.close()
        return _FakeFuture()

    with patch(
        "src.infrastructure.channels.connection_manager.asyncio.run_coroutine_threadsafe",
        side_effect=_fake_run_coroutine_threadsafe,
    ) as scheduler:
        manager._schedule_route_message(message)

    scheduler.assert_called_once()
    assert captured["loop"] is manager._main_loop


@pytest.mark.unit
def test_schedule_route_message_logs_error_without_main_loop(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Routing should fail fast when manager main loop was not initialized."""

    manager = ChannelConnectionManager()
    message = _build_message()

    with patch(
        "src.infrastructure.channels.connection_manager.asyncio.run_coroutine_threadsafe"
    ) as scheduler:
        manager._schedule_route_message(message)

    scheduler.assert_called_once()
    assert "No event loop available" in caplog.text


@pytest.mark.unit
def test_schedule_route_message_logs_error_when_scheduler_fails(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Scheduling failure should be handled without raising to caller."""

    class _Loop:
        @staticmethod
        def is_closed() -> bool:
            return False

        @staticmethod
        def is_running() -> bool:
            return True

    manager = ChannelConnectionManager()
    manager._main_loop = _Loop()  # type: ignore[assignment]
    message = _build_message()
    exception_detail = "loop closed channel-schedule-secret-1357"

    with patch(
        "src.infrastructure.channels.connection_manager.asyncio.run_coroutine_threadsafe",
        side_effect=RuntimeError(exception_detail),
    ):
        manager._schedule_route_message(message)

    assert "Failed to schedule message routing" in caplog.text
    assert exception_detail not in caplog.text
    assert "error_type=RuntimeError" in caplog.text


@pytest.mark.unit
def test_schedule_route_message_redacts_sync_router_failure(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Sync fallback routing failures should not log raw exception text."""
    exception_detail = "sync router failed channel-sync-secret-8642"

    def _router(_message: Message) -> None:
        raise RuntimeError(exception_detail)

    manager = ChannelConnectionManager(message_router=_router)

    with caplog.at_level(
        "ERROR",
        logger="src.infrastructure.channels.connection_manager",
    ):
        manager._schedule_route_message(_build_message())

    assert "Sync routing failed" in caplog.text
    assert exception_detail not in caplog.text
    assert "error_type=RuntimeError" in caplog.text


@pytest.mark.unit
def test_on_route_future_done_redacts_future_exception(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Background routing task failures should not log raw exception text."""
    manager = ChannelConnectionManager()
    future: Future[None] = Future()
    exception_detail = "future failed channel-future-secret-2468"
    future.set_exception(RuntimeError(exception_detail))

    with caplog.at_level(
        "ERROR",
        logger="src.infrastructure.channels.connection_manager",
    ):
        manager._on_route_future_done(future)

    assert "Scheduled message routing failed" in caplog.text
    assert exception_detail not in caplog.text
    assert "error_type=RuntimeError" in caplog.text


@pytest.mark.unit
@pytest.mark.asyncio
async def test_restart_connection_redacts_add_failure(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Restart failures should not log raw config IDs or exception text."""
    exception_detail = "restart failed channel-restart-secret-1357"
    secret_config_id = "channel-config-secret-2468"

    class _SessionContext:
        @staticmethod
        async def __aenter__() -> object:
            return object()

        @staticmethod
        async def __aexit__(*args: object) -> None:
            return None

    class _FakeChannelConfigRepository:
        def __init__(self, _session: object) -> None:
            pass

        async def get_by_id(self, config_id: str) -> SimpleNamespace:
            assert config_id == secret_config_id
            return SimpleNamespace(id=secret_config_id, enabled=True)

    manager = ChannelConnectionManager(session_factory=lambda: _SessionContext())
    manager.connections[secret_config_id] = ManagedConnection(
        config_id=secret_config_id,
        project_id="project-1",
        channel_type="feishu",
        adapter=object(),
        status=ConnectionStatus.CONNECTED,
    )
    manager.remove_connection = AsyncMock(return_value=True)  # type: ignore[method-assign]
    manager.add_connection = AsyncMock(  # type: ignore[method-assign]
        side_effect=RuntimeError(exception_detail)
    )

    with (
        patch(
            "src.infrastructure.channels.connection_manager.ChannelConfigRepository",
            _FakeChannelConfigRepository,
        ),
        caplog.at_level(
            "ERROR",
            logger="src.infrastructure.channels.connection_manager",
        ),
    ):
        restarted = await manager.restart_connection(secret_config_id)

    assert restarted is False
    assert "Failed to restart" in caplog.text
    assert exception_detail not in caplog.text
    assert secret_config_id not in caplog.text
    assert "error_type=RuntimeError" in caplog.text
    assert "has_config_id=True" in caplog.text


@pytest.mark.unit
@pytest.mark.asyncio
async def test_health_check_loop_redacts_loop_error(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Health check loop failures should not log raw exception text."""
    exception_detail = "health check failed channel-health-secret-1357"

    manager = ChannelConnectionManager()
    manager._started = True

    async def _sleep(_seconds: float) -> None:
        manager._started = False
        raise RuntimeError(exception_detail)

    monkeypatch.setattr("src.infrastructure.channels.connection_manager.asyncio.sleep", _sleep)

    with caplog.at_level(
        "ERROR",
        logger="src.infrastructure.channels.connection_manager",
    ):
        await manager._health_check_loop()

    assert "Health check error" in caplog.text
    assert exception_detail not in caplog.text
    assert "error_type=RuntimeError" in caplog.text


@pytest.mark.unit
@pytest.mark.asyncio
async def test_start_all_redacts_connection_start_failure(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Startup connection failures should not log raw config IDs or exception text."""
    exception_detail = "startup failed channel-start-secret-1357"
    secret_config_id = "channel-config-secret-2468"

    class _SessionContext:
        @staticmethod
        async def __aenter__() -> object:
            return object()

        @staticmethod
        async def __aexit__(*args: object) -> None:
            return None

    class _FakeOutboxRetryWorker:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        @staticmethod
        def start() -> None:
            return None

    manager = ChannelConnectionManager(session_factory=lambda: _SessionContext())
    manager._list_all_enabled = AsyncMock(  # type: ignore[method-assign]
        return_value=[
            SimpleNamespace(
                id=secret_config_id,
                enabled=True,
                channel_type="feishu",
                project_id="project-1",
            )
        ]
    )
    manager.add_connection = AsyncMock(  # type: ignore[method-assign]
        side_effect=RuntimeError(exception_detail)
    )

    fake_task = SimpleNamespace(done=lambda: False)

    def _fake_create_task(coro):
        coro.close()
        return fake_task

    with (
        patch(
            "src.infrastructure.channels.connection_manager.OutboxRetryWorker",
            _FakeOutboxRetryWorker,
        ),
        patch(
            "src.infrastructure.channels.connection_manager.asyncio.create_task",
            side_effect=_fake_create_task,
        ),
        caplog.at_level(
            "ERROR",
            logger="src.infrastructure.channels.connection_manager",
        ),
    ):
        started = await manager.start_all()

    assert started == 0
    assert "Failed to start connection" in caplog.text
    assert exception_detail not in caplog.text
    assert secret_config_id not in caplog.text
    assert "error_type=RuntimeError" in caplog.text
    assert "has_config_id=True" in caplog.text


@pytest.mark.unit
@pytest.mark.asyncio
async def test_add_connection_refreshes_closed_main_loop() -> None:
    """add_connection should refresh stale closed loop reference."""

    class _ClosedLoop:
        @staticmethod
        def is_closed() -> bool:
            return True

        @staticmethod
        def is_running() -> bool:
            return False

    manager = ChannelConnectionManager()
    manager._main_loop = _ClosedLoop()  # type: ignore[assignment]

    config = SimpleNamespace(
        id="cfg_1",
        enabled=True,
        channel_type="feishu",
        project_id="proj_1",
    )

    fake_task = SimpleNamespace(done=lambda: False)
    generation = object()
    lease = _FakeGenerationLease(generation)
    host = _FakeGenerationHost(lease)

    def _fake_create_task(coro):
        coro.close()
        return fake_task

    with (
        patch.object(manager, "_create_adapter", new=AsyncMock(return_value=object())),
        patch(
            "src.infrastructure.channels.connection_manager.current_process_generation_host_v2",
            return_value=host,
        ),
        patch(
            "src.infrastructure.channels.connection_manager.asyncio.create_task",
            side_effect=_fake_create_task,
        ),
    ):
        await manager.add_connection(config)

    assert manager._main_loop is asyncio.get_running_loop()
    assert config.id in manager.connections
    assert manager.connections[config.id]._generation_lease is lease


@pytest.mark.unit
@pytest.mark.asyncio
async def test_add_connection_refreshes_non_running_main_loop() -> None:
    """add_connection should refresh stale non-running loop reference."""

    class _StoppedLoop:
        @staticmethod
        def is_closed() -> bool:
            return False

        @staticmethod
        def is_running() -> bool:
            return False

    manager = ChannelConnectionManager()
    manager._main_loop = _StoppedLoop()  # type: ignore[assignment]

    config = SimpleNamespace(
        id="cfg_2",
        enabled=True,
        channel_type="feishu",
        project_id="proj_2",
    )

    fake_task = SimpleNamespace(done=lambda: False)
    generation = object()
    lease = _FakeGenerationLease(generation)
    host = _FakeGenerationHost(lease)

    def _fake_create_task(coro):
        coro.close()
        return fake_task

    with (
        patch.object(manager, "_create_adapter", new=AsyncMock(return_value=object())),
        patch(
            "src.infrastructure.channels.connection_manager.current_process_generation_host_v2",
            return_value=host,
        ),
        patch(
            "src.infrastructure.channels.connection_manager.asyncio.create_task",
            side_effect=_fake_create_task,
        ),
    ):
        await manager.add_connection(config)

    assert manager._main_loop is asyncio.get_running_loop()
    assert config.id in manager.connections
    assert manager.connections[config.id]._generation_lease is lease


@pytest.mark.unit
@pytest.mark.asyncio
async def test_shutdown_all_clears_main_loop() -> None:
    """shutdown_all should reset manager loop reference."""

    class _Loop:
        @staticmethod
        def is_closed() -> bool:
            return False

    manager = ChannelConnectionManager()
    manager._main_loop = _Loop()  # type: ignore[assignment]
    manager._started = True

    await manager.shutdown_all()

    assert manager._main_loop is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_create_adapter_prefers_plugin_factory() -> None:
    """Channel adapter creation should use the generation-owned resolver."""
    manager = ChannelConnectionManager()
    plugin_adapter = object()
    generation, resolver = _resolver_generation(
        metadata=None,
        build=AsyncMock(return_value=plugin_adapter),
    )
    config = SimpleNamespace(
        enabled=True,
        app_id="cli_test",
        app_secret="",
        encrypt_key=None,
        verification_token=None,
        connection_mode="websocket",
        webhook_port=None,
        webhook_path=None,
        domain="feishu",
        extra_settings={},
        channel_type="feishu",
    )

    adapter = await manager._create_adapter(config, generation)  # type: ignore[arg-type]

    assert adapter is plugin_adapter
    resolver.build.assert_awaited_once()  # type: ignore[attr-defined]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_create_adapter_decrypts_plugin_secret_paths() -> None:
    """Channel adapter context should receive decrypted values for secret_paths."""
    manager = ChannelConnectionManager()
    captured_config = {}

    async def _build_adapter(context: object) -> object:
        captured_config["channel_config"] = context.channel_config
        return object()

    from src.infrastructure.security.encryption_service import get_encryption_service

    encryption_service = get_encryption_service()
    generation, _resolver = _resolver_generation(
        metadata=SimpleNamespace(
            secret_paths=("app_secret", "encrypt_key", "verification_token", "api_token")
        ),
        build=AsyncMock(side_effect=_build_adapter),
    )
    config = SimpleNamespace(
        enabled=True,
        app_id="cli_test",
        app_secret=encryption_service.encrypt("app-secret"),
        encrypt_key=encryption_service.encrypt("encrypt-key"),
        verification_token=encryption_service.encrypt("verify-token"),
        connection_mode="websocket",
        webhook_port=None,
        webhook_path=None,
        domain="feishu",
        extra_settings={"api_token": encryption_service.encrypt("api-token")},
        channel_type="feishu",
    )

    await manager._create_adapter(config, generation)  # type: ignore[arg-type]

    channel_config = captured_config["channel_config"]
    assert channel_config.app_secret == "app-secret"
    assert channel_config.encrypt_key == "encrypt-key"
    assert channel_config.verification_token == "verify-token"
    assert channel_config.extra["api_token"] == "api-token"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_create_adapter_raises_when_plugin_adapter_missing() -> None:
    """Manager should fail closed when the generation has no requested adapter."""
    manager = ChannelConnectionManager()
    generation, _resolver = _resolver_generation(
        metadata=None,
        build=AsyncMock(
            side_effect=RuntimeV2Error(
                "channel_adapter_not_found",
                "channel type feishu has no active contribution",
            )
        ),
    )
    config = SimpleNamespace(
        enabled=True,
        app_id="cli_test",
        app_secret="",
        encrypt_key=None,
        verification_token=None,
        connection_mode="websocket",
        webhook_port=None,
        webhook_path=None,
        domain="feishu",
        extra_settings={},
        channel_type="feishu",
    )

    with pytest.raises(RuntimeV2Error) as error:
        await manager._create_adapter(config, generation)  # type: ignore[arg-type]

    assert error.value.code == "channel_adapter_not_found"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_add_connection_releases_generation_lease_when_adapter_build_fails() -> None:
    manager = ChannelConnectionManager()
    generation = object()
    lease = _FakeGenerationLease(generation)
    host = _FakeGenerationHost(lease)
    config = SimpleNamespace(
        id="cfg-failed-adapter",
        enabled=True,
        channel_type="feishu",
        project_id="project-a",
    )

    with (
        patch(
            "src.infrastructure.channels.connection_manager.current_process_generation_host_v2",
            return_value=host,
        ),
        patch.object(
            manager,
            "_create_adapter",
            new=AsyncMock(
                side_effect=RuntimeV2Error(
                    "channel_adapter_not_found",
                    "channel type feishu has no active contribution",
                )
            ),
        ),
        pytest.raises(RuntimeV2Error),
    ):
        await manager.add_connection(config)  # type: ignore[arg-type]

    assert host.acquire_calls == 1
    assert lease.release_calls == 1
    assert config.id not in manager.connections


@pytest.mark.unit
@pytest.mark.asyncio
async def test_connection_loop_releases_generation_lease_after_cleanup() -> None:
    manager = ChannelConnectionManager()
    lease = _FakeGenerationLease(object())
    connection = ManagedConnection(
        config_id="cfg-generation-lease",
        project_id="project-a",
        channel_type="feishu",
        adapter=object(),
        _generation_lease=lease,  # type: ignore[arg-type]
    )
    config = SimpleNamespace(id=connection.config_id)
    manager._attempt_connect = AsyncMock(side_effect=RuntimeError("connection failed"))  # type: ignore[method-assign]
    manager._handle_reconnect_backoff = AsyncMock(return_value=True)  # type: ignore[method-assign]
    manager._cleanup_connection = AsyncMock()  # type: ignore[method-assign]
    manager._update_db_status = AsyncMock()  # type: ignore[method-assign]

    await manager._connection_loop(connection, config)  # type: ignore[arg-type]

    manager._cleanup_connection.assert_awaited_once_with(connection, config)  # type: ignore[attr-defined]
    assert lease.release_calls == 1
    assert connection._generation_lease is None


@pytest.mark.unit
def test_channel_connection_authority_has_no_v1_plugin_runtime_dependency() -> None:
    from src.infrastructure.adapters.primary.web.startup import channels as startup_channels
    from src.infrastructure.channels import connection_manager

    source = inspect.getsource(connection_manager) + inspect.getsource(startup_channels)

    assert "get_plugin_registry" not in source
    assert "get_plugin_runtime_manager" not in source
    assert "ChannelAdapterBuildContext," not in source
