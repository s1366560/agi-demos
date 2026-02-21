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

    scheduler.assert_not_called()
    assert "Main event loop not initialized" in caplog.text


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
