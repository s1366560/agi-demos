"""Unit tests for ChannelConnectionManager scheduling behavior."""

import asyncio
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
from src.infrastructure.channels.connection_manager import ChannelConnectionManager


def _build_message() -> Message:
    return Message(
        channel="feishu",
        chat_type=ChatType.P2P,
        chat_id="chat_1",
        sender=SenderInfo(id="ou_sender"),
        content=MessageContent(type=MessageType.TEXT, text="hello"),
    )


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

    with patch(
        "src.infrastructure.channels.connection_manager.asyncio.run_coroutine_threadsafe",
        side_effect=RuntimeError("loop closed"),
    ):
        manager._schedule_route_message(message)

    assert "Failed to schedule message routing" in caplog.text


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

    def _fake_create_task(coro):
        coro.close()
        return fake_task

    with (
        patch.object(manager, "_create_adapter", new=AsyncMock(return_value=object())),
        patch(
            "src.infrastructure.channels.connection_manager.asyncio.create_task",
            side_effect=_fake_create_task,
        ),
    ):
        await manager.add_connection(config)

    assert manager._main_loop is asyncio.get_running_loop()
    assert config.id in manager.connections


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

    def _fake_create_task(coro):
        coro.close()
        return fake_task

    with (
        patch.object(manager, "_create_adapter", new=AsyncMock(return_value=object())),
        patch(
            "src.infrastructure.channels.connection_manager.asyncio.create_task",
            side_effect=_fake_create_task,
        ),
    ):
        await manager.add_connection(config)

    assert manager._main_loop is asyncio.get_running_loop()
    assert config.id in manager.connections


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
    """Channel adapter creation should prefer plugin-registered factories."""
    manager = ChannelConnectionManager()
    plugin_adapter = object()
    plugin_registry = SimpleNamespace(
        list_channel_type_metadata=lambda: {},
        build_channel_adapter=AsyncMock(return_value=(plugin_adapter, []))
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

    with patch(
        "src.infrastructure.agent.plugins.registry.get_plugin_registry",
        return_value=plugin_registry,
    ):
        adapter = await manager._create_adapter(config)

    assert adapter is plugin_adapter
    plugin_registry.build_channel_adapter.assert_awaited_once()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_create_adapter_decrypts_plugin_secret_paths() -> None:
    """Channel adapter context should receive decrypted values for secret_paths."""
    manager = ChannelConnectionManager()
    captured_config = {}

    async def _build_adapter(context):
        captured_config["channel_config"] = context.channel_config
        return object(), []

    from src.infrastructure.security.encryption_service import get_encryption_service

    encryption_service = get_encryption_service()
    plugin_registry = SimpleNamespace(
        list_channel_type_metadata=lambda: {
            "feishu": SimpleNamespace(
                secret_paths=["app_secret", "encrypt_key", "verification_token", "api_token"]
            )
        },
        build_channel_adapter=AsyncMock(side_effect=_build_adapter),
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

    with patch(
        "src.infrastructure.agent.plugins.registry.get_plugin_registry",
        return_value=plugin_registry,
    ):
        await manager._create_adapter(config)

    channel_config = captured_config["channel_config"]
    assert channel_config.app_secret == "app-secret"
    assert channel_config.encrypt_key == "encrypt-key"
    assert channel_config.verification_token == "verify-token"
    assert channel_config.extra["api_token"] == "api-token"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_create_adapter_raises_when_plugin_adapter_missing() -> None:
    """Manager should fail fast when no plugin provides requested channel adapter."""
    manager = ChannelConnectionManager()
    plugin_registry = SimpleNamespace(
        list_channel_type_metadata=lambda: {},
        build_channel_adapter=AsyncMock(return_value=(None, [])),
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

    with patch(
        "src.infrastructure.agent.plugins.registry.get_plugin_registry",
        return_value=plugin_registry,
    ), pytest.raises(ValueError, match="Unsupported channel type"):
        await manager._create_adapter(config)
