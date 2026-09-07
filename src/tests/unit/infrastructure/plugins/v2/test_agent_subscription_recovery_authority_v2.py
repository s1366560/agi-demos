"""Pinned V2 authority coverage for WebSocket subscription recovery."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.adapters.primary.web.websocket.handlers import subscription_handler
from src.infrastructure.adapters.primary.web.websocket.handlers.subscription_handler import (
    SubscribeHandler,
)
from src.infrastructure.plugins.v2 import (
    agent_recovery_stream_services as recovery_stream_module,
    conversation_access_services as conversation_module,
    session_event_log_store as store_module,
)
from src.infrastructure.plugins.v2.boundary import (
    OPERATION_DB_SESSION_SERVICE_V2,
    clear_process_generation_host_v2,
    current_generation_v2,
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


class _ScopedRecoveryAuthority:
    """Real scope registry with an independent ROOT conversation-access host."""

    def __init__(self, definitions):
        from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
        from src.infrastructure.plugins.v2.scoped_runtime_registry import ScopedRuntimeRegistryV2

        self.scope = ScopeV2(
            kind=ScopeKindV2.SESSION,
            tenant_id="tenant-1",
            project_id="project-1",
            session_id="conversation-1",
        )
        self.registry = ScopedRuntimeRegistryV2(definitions)
        self.root = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
        self.manager = None

    async def bootstrap(self, *, profile_path, manifest_paths, generation, version):
        import json

        from src.domain.model.plugins.generated_v2 import ServiceRequiredV2
        from src.infrastructure.plugins.v2.composer import (
            compose_profile_v2,
            load_profile_document_v2,
        )
        from src.infrastructure.plugins.v2.protocol import (
            control_envelope_v2,
            parse_plugin_manifest_v2,
        )
        from src.infrastructure.plugins.v2.service_closure import project_service_closure_v2

        manifests = [
            parse_plugin_manifest_v2(json.loads(path.read_text())) for path in manifest_paths
        ]
        snapshot = compose_profile_v2(
            load_profile_document_v2(profile_path),
            {m.plugin_id: m for m in manifests},
            generation=generation,
        )

        def project(services):
            return project_service_closure_v2(
                snapshot,
                scope=self.scope,
                required_services=tuple(
                    ServiceRequiredV2(alias=str(i), service=service, version="1.0.0")
                    for i, service in enumerate(services)
                ),
            )

        if self.root.manager.current is None:
            root_snapshot = project(("service:application.conversation-access",))
            assert (
                await self.root.apply(
                    root_snapshot, control_envelope_v2(root_snapshot, version=version)
                )
            ).accepted
        scoped_snapshot = project(
            (
                "service:agent.recovery-stream",
                "service:session-event-log",
                "service:agent.worker-runtime",
            )
        )
        publication = await self.registry.publish(
            self.scope, scoped_snapshot, control_envelope_v2(scoped_snapshot, version=version)
        )
        reservation = await self.registry.acquire_bound(self.scope)
        self.manager = reservation.host._slot.host.manager
        await reservation.lease.release()
        return publication

    async def acquire_existing(self, context, *, conversation_id, project_id):
        assert context.tenant_id == self.scope.tenant_id
        assert conversation_id == self.scope.session_id
        assert project_id == self.scope.project_id
        reservation = await self.registry.acquire_bound(self.scope)
        assert reservation.lease.generation is not self.root.manager.current
        return reservation

    async def close(self):
        await self.registry.close()
        await self.root.close()


class _TrackedRedisClient:
    def __init__(self, name: str) -> None:
        self.name = name
        self.calls: list[str] = []
        self.cache_patterns: list[str] = []
        self.cache_deletes: list[tuple[str | bytes, ...]] = []
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

    async def scan_iter(self, *, match: str, count: int) -> Any:
        assert count == 100
        self.cache_patterns.append(match)
        if False:
            yield "unreachable"

    async def delete(self, *keys: str | bytes) -> int:
        self.cache_deletes.append(keys)
        return len(keys)

    async def xadd(self, *_args: object, **_kwargs: object) -> object:
        raise AssertionError("Redis stream publication is outside this authority fixture")

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
    host = _ScopedRecoveryAuthority(
        builtin_runtime_definitions_v2(redis_runtime_factory=redis_factory)
    )
    first = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=941,
        version=941,
    )
    assert first.accepted is True
    install_process_generation_host_v2(host.root)
    monkeypatch.setattr(
        subscription_handler, "acquire_existing_scoped_session_v2", host.acquire_existing
    )
    monkeypatch.setattr(subscription_handler, "authorize_existing_scoped_session_v2", AsyncMock())

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
        async with pin_generation_v2(host.root):
            await SubscribeHandler().handle(context, {"conversation_id": "conversation-1"})
            assert first_client.close_calls == 1

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
        clear_process_generation_host_v2(host.root)
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
    host = _ScopedRecoveryAuthority(builtin_runtime_definitions_v2())
    publication = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=943,
        version=943,
    )
    assert publication.accepted is True
    install_process_generation_host_v2(host.root)
    monkeypatch.setattr(
        subscription_handler, "acquire_existing_scoped_session_v2", host.acquire_existing
    )
    monkeypatch.setattr(subscription_handler, "authorize_existing_scoped_session_v2", AsyncMock())
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
        async with pin_generation_v2(host.root):
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
        clear_process_generation_host_v2(host.root)
        await db.close()
        await host.close()


async def test_detached_recovery_stream_keeps_exact_generation_after_reload(  # noqa: PLR0915
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

    monkeypatch.setattr(store_module, "SqlSessionEventLogStoreV2", lambda: next(stores))
    host = _ScopedRecoveryAuthority(
        builtin_runtime_definitions_v2(redis_runtime_factory=redis_factory)
    )
    first = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=949,
        version=949,
    )
    assert first.accepted is True
    install_process_generation_host_v2(host.root)
    monkeypatch.setattr(
        subscription_handler, "acquire_existing_scoped_session_v2", host.acquire_existing
    )
    monkeypatch.setattr(subscription_handler, "authorize_existing_scoped_session_v2", AsyncMock())

    async def reload_generation() -> None:
        second = await host.bootstrap(
            profile_path=_PROFILE_PATH,
            manifest_paths=(_MANIFEST_PATH,),
            generation=950,
            version=950,
        )
        assert second.accepted is True

    first_client.reload_generation = reload_generation
    static_probe = _StaticRecoveryAuthorityProbe()
    parent_db = AsyncSession()
    detached_db = AsyncSession()
    context = _message_context(static_probe, parent_db)
    context.session_id = "session-1"
    created_tasks: list[asyncio.Task[None]] = []

    @asynccontextmanager
    async def fresh_db_context():
        yield SimpleNamespace(db=detached_db, session_id="session-1")

    context.fresh_db_context = fresh_db_context

    async def try_start_bridge_task(**kwargs: object) -> bool:
        task_factory = kwargs["task_factory"]
        assert callable(task_factory)
        task = task_factory()
        assert isinstance(task, asyncio.Task)
        created_tasks.append(task)
        return True

    context.connection_manager.try_start_bridge_task.side_effect = try_start_bridge_task
    stream_service = object()
    resolved: list[tuple[int, str, object, object]] = []

    async def resolve_recovery_stream(
        self: recovery_stream_module.AgentRecoveryStreamResolverV2,
        operation: Any,
    ) -> object:
        generation = current_generation_v2()
        resolved.append(
            (
                generation.descriptor.generation,
                self.redis.client.name,
                operation.require(OPERATION_DB_SESSION_SERVICE_V2),
                operation,
            )
        )
        return stream_service

    monkeypatch.setattr(
        recovery_stream_module.AgentRecoveryStreamResolverV2,
        "resolve",
        resolve_recovery_stream,
    )
    stream_started = asyncio.Event()
    stream_resume = asyncio.Event()

    async def blocked_stream(**_kwargs: object) -> None:
        stream_started.set()
        await stream_resume.wait()

    stream = AsyncMock(side_effect=blocked_stream)
    monkeypatch.setattr(subscription_handler, "stream_hitl_response_to_websocket", stream)

    def conversation_repository(db: AsyncSession) -> Any:
        return static_probe._conversation_repository

    monkeypatch.setattr(
        conversation_module,
        "SqlConversationRepository",
        conversation_repository,
    )

    try:
        async with pin_generation_v2(host.root):
            await SubscribeHandler().handle(context, {"conversation_id": "conversation-1"})

        await asyncio.wait_for(stream_started.wait(), timeout=1)
        assert first_client.close_calls == 0
        assert created_tasks and all(not task.done() for task in created_tasks)
        assert host.manager.current is not None
        assert host.manager.current.generation == 950
        stream_resume.set()
        await asyncio.wait_for(asyncio.gather(*created_tasks), timeout=1)

        assert [(generation, redis_name, db) for generation, redis_name, db, _ in resolved] == [
            (949, "first", detached_db)
        ]
        stream.assert_awaited_once()
        assert stream.call_args.kwargs["agent_service"] is stream_service
        assert first_client.close_calls == 1
        assert second_client.close_calls == 0
        assert static_probe.redis_accesses == 0
        assert static_probe.event_repository_accesses == 0
    finally:
        stream_resume.set()
        await asyncio.wait_for(asyncio.gather(*created_tasks), timeout=1)
        clear_process_generation_host_v2(host.root)
        await parent_db.close()
        await detached_db.close()
        await host.close()

    assert second_client.close_calls == 1
