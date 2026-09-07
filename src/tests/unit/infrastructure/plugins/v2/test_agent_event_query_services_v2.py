"""V2 Provider/Consumer coverage for Agent event replay and status queries."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.plugins.v2.agent_event_query_services import (
    AGENT_EVENT_QUERY_MODULE_V2,
    AGENT_EVENT_QUERY_REDIS_INJECT_V2,
    AGENT_EVENT_QUERY_REPOSITORIES_INJECT_V2,
    AGENT_EVENT_QUERY_REPOSITORY_PROVIDER_MODULE_V2,
    AGENT_EVENT_QUERY_SERVICE_V2,
    AgentEventQueryResolverV2,
    AgentEventQueryServiceV2,
)
from src.infrastructure.plugins.v2.boundary import OPERATION_DB_SESSION_SERVICE_V2
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.composer import compose_profile_v2, load_profile_document_v2
from src.infrastructure.plugins.v2.protocol import parse_plugin_manifest_v2
from src.infrastructure.plugins.v2.runtime import LoaderV2, OperationContextV2, RuntimeV2Error
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[6]
_PROFILE_PATH = _ROOT / "config/plugin-profiles/memstack-default.v2.yaml"
_MANIFEST_PATH = _ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json"
_ROUTER_PATH = _ROOT / "src/infrastructure/adapters/primary/web/routers/agent/events.py"


class _RedisClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []
        self.close_calls = 0

    async def get(self, key: str) -> bytes | None:
        self.calls.append(("get", key))
        return b"message-a"

    async def xinfo_stream(self, key: str) -> dict[str, int]:
        self.calls.append(("xinfo_stream", key))
        return {"length": 1}

    async def xrevrange(
        self,
        key: str,
        *,
        count: int,
    ) -> list[tuple[bytes, dict[bytes, bytes]]]:
        self.calls.append(("xrevrange", key))
        assert count == 1
        return [(b"1-0", {b"event_time_us": b"125"})]

    async def scan_iter(self, *, match: str, count: int) -> Any:
        del match, count
        if False:
            yield "unreachable"

    async def delete(self, *keys: str | bytes) -> int:
        return len(keys)

    async def xadd(self, *_args: object, **_kwargs: object) -> str:
        return "1-0"

    async def aclose(self) -> None:
        self.close_calls += 1


async def test_event_query_resolver_uses_operation_session_and_generation_redis() -> None:
    redis_client = _RedisClient()
    replacement_client = _RedisClient()
    clients = iter((redis_client, replacement_client))

    async def redis_factory() -> _RedisClient:
        return next(clients)

    host = PlatformPluginRuntimeHostV2(
        builtin_runtime_definitions_v2(redis_runtime_factory=redis_factory)
    )
    publication = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=996,
        version=996,
    )
    assert publication.accepted is True
    db = AsyncSession()
    try:
        async with (
            await host.acquire() as generation,
            OperationContextV2(
                generation=generation,
                operation_id="agent-event-query:root",
                scope=ScopeV2(kind=ScopeKindV2.ROOT),
            ) as operation,
        ):
            _ = operation.provide(OPERATION_DB_SESSION_SERVICE_V2, db)
            resolver = operation.require(AGENT_EVENT_QUERY_SERVICE_V2)

            assert isinstance(resolver, AgentEventQueryResolverV2)
            service = resolver.resolve(operation)
            assert getattr(service.event_repository, "_session", None) is db
            assert service.redis_client is redis_client
            replacement = await host.bootstrap(
                profile_path=_PROFILE_PATH,
                manifest_paths=(_MANIFEST_PATH,),
                generation=997,
                version=997,
            )
            assert replacement.accepted is True
            assert redis_client.close_calls == 0
            assert service.redis_client is redis_client

        assert redis_client.close_calls == 1
    finally:
        await db.close()
        await host.close()

    assert replacement_client.close_calls == 1


def test_event_query_modules_are_explicit_ordered_profile_entries() -> None:
    document = load_profile_document_v2(_PROFILE_PATH)
    enabled_modules = tuple(entry.module_ref for entry in document.entries if entry.enabled)

    assert AGENT_EVENT_QUERY_REPOSITORY_PROVIDER_MODULE_V2 in enabled_modules
    assert AGENT_EVENT_QUERY_MODULE_V2 in enabled_modules
    assert enabled_modules.index(AGENT_EVENT_QUERY_REPOSITORY_PROVIDER_MODULE_V2) < (
        enabled_modules.index(AGENT_EVENT_QUERY_MODULE_V2)
    )
    application_entry = next(
        entry for entry in document.entries if entry.module_ref == AGENT_EVENT_QUERY_MODULE_V2
    )
    assert application_entry.inject == {
        AGENT_EVENT_QUERY_REPOSITORIES_INJECT_V2: (
            "service:persistence.agent-event-query-repository-provider"
        ),
        AGENT_EVENT_QUERY_REDIS_INJECT_V2: "service:runtime.redis-client",
    }


async def test_event_query_rejects_missing_provider_without_fallback() -> None:
    document = load_profile_document_v2(_PROFILE_PATH)
    disabled = replace(
        document,
        entries=tuple(
            replace(entry, enabled=False)
            if entry.module_ref == AGENT_EVENT_QUERY_REPOSITORY_PROVIDER_MODULE_V2
            else entry
            for entry in document.entries
        ),
    )
    manifest = parse_plugin_manifest_v2(json.loads(_MANIFEST_PATH.read_text(encoding="utf-8")))
    snapshot = compose_profile_v2(disabled, {manifest.plugin_id: manifest}, generation=997)

    with pytest.raises(RuntimeV2Error) as error:
        await LoaderV2(builtin_runtime_definitions_v2()).stage(snapshot)

    assert error.value.code == "missing_inject_provider"
    assert "builtin-agent-event-query" in str(error.value)


async def test_event_query_rejects_missing_redis_inject_without_fallback() -> None:
    document = load_profile_document_v2(_PROFILE_PATH)
    invalid = replace(
        document,
        entries=tuple(
            replace(
                entry,
                inject={
                    alias: service
                    for alias, service in entry.inject.items()
                    if alias != AGENT_EVENT_QUERY_REDIS_INJECT_V2
                },
            )
            if entry.module_ref == AGENT_EVENT_QUERY_MODULE_V2
            else entry
            for entry in document.entries
        ),
    )
    manifest = parse_plugin_manifest_v2(json.loads(_MANIFEST_PATH.read_text(encoding="utf-8")))
    snapshot = compose_profile_v2(invalid, {manifest.plugin_id: manifest}, generation=997)

    with pytest.raises(RuntimeV2Error) as error:
        await LoaderV2(builtin_runtime_definitions_v2()).stage(snapshot)

    assert error.value.code == "missing_required_inject"
    assert "builtin-agent-event-query" in str(error.value)


async def test_event_query_resolver_rejects_non_session_operation_service() -> None:
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    publication = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=998,
        version=998,
    )
    assert publication.accepted is True
    try:
        async with (
            await host.acquire() as generation,
            OperationContextV2(
                generation=generation,
                operation_id="agent-event-query:invalid-db",
                scope=ScopeV2(kind=ScopeKindV2.ROOT),
            ) as operation,
        ):
            _ = operation.provide(OPERATION_DB_SESSION_SERVICE_V2, object())
            resolver = operation.require(AGENT_EVENT_QUERY_SERVICE_V2)
            assert isinstance(resolver, AgentEventQueryResolverV2)

            with pytest.raises(RuntimeV2Error) as error:
                _ = resolver.resolve(operation)

            assert error.value.code == "invalid_operation_db_session"
    finally:
        await host.close()


async def test_event_query_application_delegates_replay_and_builds_status() -> None:
    event = SimpleNamespace(message_id="message-a")
    repository = SimpleNamespace(
        get_events=AsyncMock(return_value=[event]),
        get_last_event_time=AsyncMock(return_value=(100, 7)),
    )
    redis_client = _RedisClient()
    service = AgentEventQueryServiceV2(
        event_repository=cast(Any, repository),
        redis_client=redis_client,
    )

    events = await service.get_events(
        conversation_id="conversation-a",
        from_time_us=11,
        from_counter=3,
        limit=17,
    )
    status = await service.get_execution_status(
        conversation_id="conversation-a",
        include_recovery=True,
        from_time_us=50,
    )

    assert events == [event]
    repository.get_events.assert_awaited_once_with(
        conversation_id="conversation-a",
        from_time_us=11,
        from_counter=3,
        limit=17,
    )
    assert status.is_running is True
    assert status.current_message_id == "message-a"
    assert status.last_event_time_us == 100
    assert status.last_event_counter == 7
    assert status.recovery is not None
    assert status.recovery.can_recover is True
    assert status.recovery.stream_exists is True
    assert status.recovery.recovery_source == "stream"
    assert redis_client.calls == [
        ("get", "agent:running:conversation-a"),
        ("xinfo_stream", "agent:events:conversation-a"),
        ("xrevrange", "agent:events:conversation-a"),
    ]


async def test_event_query_status_uses_database_when_redis_is_unavailable() -> None:
    repository = SimpleNamespace(
        get_last_event_time=AsyncMock(return_value=(100, 7)),
        get_events=AsyncMock(return_value=[SimpleNamespace(message_id="message-db")]),
    )
    service = AgentEventQueryServiceV2(
        event_repository=cast(Any, repository),
        redis_client=None,
    )

    status = await service.get_execution_status(
        conversation_id="conversation-a",
        include_recovery=True,
        from_time_us=125,
    )

    assert status.is_running is False
    assert status.current_message_id == "message-db"
    assert status.recovery is not None
    assert status.recovery.can_recover is False
    assert status.recovery.stream_exists is False
    assert status.recovery.recovery_source == "database"


def test_event_routes_have_no_static_container_event_or_redis_authority() -> None:
    source = _ROUTER_PATH.read_text(encoding="utf-8")

    assert "get_container_with_db" not in source
    assert "container.agent_execution_event_repository" not in source
    assert "container.redis" not in source
