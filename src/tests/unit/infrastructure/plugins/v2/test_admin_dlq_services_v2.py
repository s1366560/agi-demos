"""V2 Provider/Consumer coverage for the admin dead-letter queue."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.adapters.secondary.messaging.redis_dlq import RedisDLQAdapter
from src.infrastructure.adapters.secondary.messaging.redis_unified_event_bus import (
    RedisUnifiedEventBusAdapter,
)
from src.infrastructure.plugins.v2.admin_dlq_services import (
    ADMIN_DLQ_APPLICATION_MODULE_V2,
    ADMIN_DLQ_APPLICATION_SERVICE_V2,
    ADMIN_DLQ_PROVIDER_MODULE_V2,
    AdminDlqApplicationResolverV2,
)
from src.infrastructure.plugins.v2.agent_orchestration_runtime import (
    AGENT_ORCHESTRATION_RUNTIME_MODULE_V2,
)
from src.infrastructure.plugins.v2.agent_worker_runtime import AGENT_WORKER_RUNTIME_MODULE_V2
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.composer import compose_profile_v2, load_profile_document_v2
from src.infrastructure.plugins.v2.protocol import parse_plugin_manifest_v2
from src.infrastructure.plugins.v2.redis_runtime import (
    REDIS_RUNTIME_MODULE_V2,
    REDIS_RUNTIME_SERVICE_V2,
    RedisRuntimeServiceV2,
)
from src.infrastructure.plugins.v2.runtime import LoaderV2, OperationContextV2, RuntimeV2Error
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[6]
_PROFILE_PATH = _ROOT / "config/plugin-profiles/memstack-default.v2.yaml"
_MANIFEST_PATH = _ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json"


async def _host(
    *,
    generation: int,
    redis_client: object | None = None,
) -> PlatformPluginRuntimeHostV2:
    host = PlatformPluginRuntimeHostV2(
        builtin_runtime_definitions_v2(sandbox_redis_client=redis_client)
    )
    publication = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=generation,
        version=generation,
    )
    assert publication.accepted is True
    return host


def test_provider_and_consumer_are_independent_ordered_profile_entries() -> None:
    document = load_profile_document_v2(_PROFILE_PATH)
    enabled_modules = tuple(entry.module_ref for entry in document.entries if entry.enabled)

    assert REDIS_RUNTIME_MODULE_V2 in enabled_modules
    assert ADMIN_DLQ_PROVIDER_MODULE_V2 in enabled_modules
    assert ADMIN_DLQ_APPLICATION_MODULE_V2 in enabled_modules
    assert (
        enabled_modules.index(REDIS_RUNTIME_MODULE_V2)
        < enabled_modules.index(ADMIN_DLQ_PROVIDER_MODULE_V2)
        < enabled_modules.index(ADMIN_DLQ_APPLICATION_MODULE_V2)
    )


async def test_resolver_builds_redis_dlq_with_real_republish_adapter() -> None:
    redis_client = object()
    host = await _host(generation=120, redis_client=redis_client)
    try:
        async with (
            await host.acquire() as generation,
            OperationContextV2(
                generation=generation,
                operation_id="http-admin-dlq:resolver",
                scope=ScopeV2(kind=ScopeKindV2.ROOT),
            ) as operation,
        ):
            resolver = operation.require(ADMIN_DLQ_APPLICATION_SERVICE_V2)
            assert isinstance(resolver, AdminDlqApplicationResolverV2)
            redis_runtime = operation.require(REDIS_RUNTIME_SERVICE_V2)
            assert isinstance(redis_runtime, RedisRuntimeServiceV2)
            assert redis_runtime.client is redis_client

            queue = resolver.resolve(operation).queue

            assert isinstance(queue, RedisDLQAdapter)
            assert queue._redis is redis_client
            assert isinstance(queue._event_bus, RedisUnifiedEventBusAdapter)
            assert queue._event_bus._redis is redis_client
    finally:
        await host.close()


async def test_bootstrap_without_redis_loads_but_resolve_fails_structured() -> None:
    host = await _host(generation=121)
    try:
        async with (
            await host.acquire() as generation,
            OperationContextV2(
                generation=generation,
                operation_id="http-admin-dlq:no-redis",
                scope=ScopeV2(kind=ScopeKindV2.ROOT),
            ) as operation,
        ):
            resolver = operation.require(ADMIN_DLQ_APPLICATION_SERVICE_V2)

            with pytest.raises(RuntimeV2Error) as error:
                resolver.resolve(operation)

            assert error.value.code == "admin_dlq_redis_unavailable"
    finally:
        await host.close()


async def test_consumer_rejects_missing_provider_without_fallback() -> None:
    document = load_profile_document_v2(_PROFILE_PATH)
    disabled = replace(
        document,
        entries=tuple(
            replace(entry, enabled=False)
            if entry.module_ref == ADMIN_DLQ_PROVIDER_MODULE_V2
            else entry
            for entry in document.entries
        ),
    )
    manifest = parse_plugin_manifest_v2(json.loads(_MANIFEST_PATH.read_text(encoding="utf-8")))
    snapshot = compose_profile_v2(
        disabled,
        {manifest.plugin_id: manifest},
        generation=122,
    )

    with pytest.raises(RuntimeV2Error) as error:
        await LoaderV2(builtin_runtime_definitions_v2()).stage(snapshot)

    assert error.value.code == "missing_inject_provider"
    assert "builtin-admin-dlq-services" in str(error.value)


async def test_provider_rejects_missing_redis_runtime_inject_without_fallback() -> None:
    document = load_profile_document_v2(_PROFILE_PATH)
    disabled = replace(
        document,
        entries=tuple(
            replace(entry, enabled=False)
            if entry.module_ref
            in {
                AGENT_ORCHESTRATION_RUNTIME_MODULE_V2,
                AGENT_WORKER_RUNTIME_MODULE_V2,
                REDIS_RUNTIME_MODULE_V2,
                ADMIN_DLQ_APPLICATION_MODULE_V2,
            }
            else entry
            for entry in document.entries
        ),
    )
    manifest = parse_plugin_manifest_v2(json.loads(_MANIFEST_PATH.read_text(encoding="utf-8")))
    snapshot = compose_profile_v2(
        disabled,
        {manifest.plugin_id: manifest},
        generation=123,
    )

    with pytest.raises(RuntimeV2Error) as error:
        await LoaderV2(builtin_runtime_definitions_v2()).stage(snapshot)

    assert error.value.code == "missing_inject_provider"
    assert "builtin-admin-dlq-provider" in str(error.value)
    assert "service:runtime.redis-client" in str(error.value)
