"""Pinned V2 authority coverage for WebSocket subscription recovery."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.adapters.primary.web.websocket.handlers.subscription_handler import (
    SubscribeHandler,
)
from src.infrastructure.plugins.v2 import (
    conversation_access_services as conversation_module,
    session_event_log_store as store_module,
)
from src.infrastructure.plugins.v2.boundary import (
    clear_process_generation_host_v2,
    install_process_generation_host_v2,
    pin_generation_v2,
)
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2
from src.infrastructure.plugins.v2.session_event_log_types import (
    SessionEventCursorV2,
    SessionEventRecordV2,
)

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[6]
_PROFILE_PATH = _ROOT / "config/plugin-profiles/memstack-default.v2.yaml"
_MANIFEST_PATH = _ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json"


class _TrackedRedisClient:
    def __init__(self, name: str) -> None:
        self.name = name
        self.calls: list[str] = []
        self.close_calls = 0
        self.reload_generation = None

    async def get(self, key: str) -> bytes | None:
        self.calls.append(key)
        reload_generation = self.reload_generation
        self.reload_generation = None
        if reload_generation is not None:
            await reload_generation()
        if key == "agent:running:conversation-1":
            return b"message-1"
        return None

    async def aclose(self) -> None:
        self.close_calls += 1


class _TrackedSessionEventLogStore:
    def __init__(self, name: str) -> None:
        self.name = name
        self.message_reads: list[tuple[str, str]] = []

    async def read_message_events(
        self,
        *,
        conversation_id: str,
        message_id: str,
    ) -> list[SessionEventRecordV2]:
        self.message_reads.append((conversation_id, message_id))
        return [
            SessionEventRecordV2(
                event_id=f"{self.name}-event",
                conversation_id=conversation_id,
                message_id=message_id,
                event_type="text_delta",
                event_data={"delta": self.name},
                cursor=SessionEventCursorV2(event_time_us=320, event_counter=7),
            )
        ]


class _StaticRecoveryAuthorityProbe:
    def __init__(self) -> None:
        self.redis_accesses = 0
        self.event_repository_accesses = 0
        self.conversation_repository_accesses = 0
        self._conversation_repository = SimpleNamespace(
            find_by_id=AsyncMock(
                return_value=SimpleNamespace(
                    id="conversation-1",
                    project_id="project-1",
                    tenant_id="tenant-1",
                    user_id="user-1",
                )
            )
        )
        self._redis = SimpleNamespace(
            get=AsyncMock(return_value=b"static-message"),
        )
        self._event_repository = SimpleNamespace(
            get_events_by_message=AsyncMock(
                return_value=[
                    SimpleNamespace(
                        conversation_id="conversation-1",
                        event_type="text_delta",
                        event_time_us=999,
                        event_counter=1,
                    )
                ]
            )
        )

    def conversation_repository(self) -> Any:
        self.conversation_repository_accesses += 1
        return self._conversation_repository

    def redis(self) -> Any:
        self.redis_accesses += 1
        return self._redis

    def agent_execution_event_repository(self) -> Any:
        self.event_repository_accesses += 1
        return self._event_repository


def _message_context(
    probe: _StaticRecoveryAuthorityProbe,
    db: AsyncSession,
) -> SimpleNamespace:
    connection_manager = SimpleNamespace(
        subscribe=AsyncMock(),
        try_start_bridge_task=AsyncMock(return_value=False),
    )
    return SimpleNamespace(
        user_id="user-1",
        tenant_id="tenant-1",
        session_id="session-1",
        db=db,
        connection_manager=connection_manager,
        get_scoped_container=lambda: probe,
        send_ack=AsyncMock(),
        send_error=AsyncMock(),
    )


async def test_subscription_recovery_keeps_one_generation_for_redis_and_session_log(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_client = _TrackedRedisClient("first")
    second_client = _TrackedRedisClient("second")
    redis_clients = iter((first_client, second_client))
    first_store = _TrackedSessionEventLogStore("first")
    second_store = _TrackedSessionEventLogStore("second")
    stores = iter((first_store, second_store))

    async def redis_factory() -> _TrackedRedisClient:
        return next(redis_clients)

    monkeypatch.setattr(
        store_module,
        "SqlSessionEventLogStoreV2",
        lambda: next(stores),
    )
    host = PlatformPluginRuntimeHostV2(
        builtin_runtime_definitions_v2(redis_runtime_factory=redis_factory)
    )
    first = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=941,
        version=941,
    )
    assert first.accepted is True
    install_process_generation_host_v2(host)

    async def reload_generation() -> None:
        second = await host.bootstrap(
            profile_path=_PROFILE_PATH,
            manifest_paths=(_MANIFEST_PATH,),
            generation=942,
            version=942,
        )
        assert second.accepted is True
        assert first_client.close_calls == 0

    first_client.reload_generation = reload_generation
    static_probe = _StaticRecoveryAuthorityProbe()
    repository_sessions: list[AsyncSession] = []

    def conversation_repository(db: AsyncSession) -> Any:
        repository_sessions.append(db)
        return static_probe._conversation_repository

    monkeypatch.setattr(
        conversation_module,
        "SqlConversationRepository",
        conversation_repository,
    )
    db = AsyncSession()
    context = _message_context(static_probe, db)

    try:
        async with pin_generation_v2(host):
            await SubscribeHandler().handle(context, {"conversation_id": "conversation-1"})
            assert first_client.close_calls == 0

        assert first_client.calls == ["agent:running:conversation-1"]
        assert second_client.calls == []
        assert first_store.message_reads == [("conversation-1", "message-1")]
        assert second_store.message_reads == []
        assert repository_sessions == [db]
        assert static_probe.conversation_repository_accesses == 0
        assert static_probe.redis_accesses == 0
        assert static_probe.event_repository_accesses == 0
        assert first_client.close_calls == 1
        assert second_client.close_calls == 0
        context.connection_manager.try_start_bridge_task.assert_awaited_once()
        context.send_ack.assert_awaited_once_with(
            "subscribe",
            conversation_id="conversation-1",
        )
        context.send_error.assert_not_awaited()
    finally:
        clear_process_generation_host_v2(host)
        await db.close()
        await host.close()

    assert second_client.close_calls == 1


async def test_subscription_recovery_does_not_fallback_when_v2_redis_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _TrackedSessionEventLogStore("only")
    monkeypatch.setattr(
        store_module,
        "SqlSessionEventLogStoreV2",
        lambda: store,
    )
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    publication = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=943,
        version=943,
    )
    assert publication.accepted is True
    install_process_generation_host_v2(host)
    static_probe = _StaticRecoveryAuthorityProbe()
    repository_sessions: list[AsyncSession] = []

    def conversation_repository(db: AsyncSession) -> Any:
        repository_sessions.append(db)
        return static_probe._conversation_repository

    monkeypatch.setattr(
        conversation_module,
        "SqlConversationRepository",
        conversation_repository,
    )
    db = AsyncSession()
    context = _message_context(static_probe, db)

    try:
        async with pin_generation_v2(host):
            await SubscribeHandler().handle(context, {"conversation_id": "conversation-1"})

        assert repository_sessions == [db]
        assert static_probe.conversation_repository_accesses == 0
        assert static_probe.redis_accesses == 0
        assert static_probe.event_repository_accesses == 0
        assert store.message_reads == []
        context.connection_manager.try_start_bridge_task.assert_not_awaited()
        context.send_ack.assert_awaited_once_with(
            "subscribe",
            conversation_id="conversation-1",
        )
        context.send_error.assert_not_awaited()
    finally:
        clear_process_generation_host_v2(host)
        await db.close()
        await host.close()
