"""Generation-owned HTTP service registry coverage for sandbox previews."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.composer import load_profile_document_v2
from src.infrastructure.plugins.v2.runtime import RuntimeV2Error
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2
from src.infrastructure.plugins.v2.sandbox_http_service_registry import (
    SANDBOX_HTTP_SERVICE_REGISTRY_MODULE_V2,
    SANDBOX_HTTP_SERVICE_REGISTRY_SERVICE_V2,
    SandboxHttpServiceRegistryV2,
)

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[6]
_PROFILE_PATH = _ROOT / "config/plugin-profiles/memstack-default.v2.yaml"
_MANIFEST_PATH = _ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json"


class _FakeRedisClient:
    def __init__(self) -> None:
        self.hashes: dict[str, dict[str, str]] = {}

    async def hget(self, key: str, field: str) -> str | None:
        return self.hashes.get(key, {}).get(field)

    async def hset(self, key: str, field: str, value: str) -> None:
        self.hashes.setdefault(key, {})[field] = value

    async def hgetall(self, key: str) -> dict[bytes, bytes]:
        return {
            field.encode(): payload.encode() for field, payload in self.hashes.get(key, {}).items()
        }

    async def eval(self, _script: str, _key_count: int, key: str, field: str) -> str | None:
        values = self.hashes.get(key, {})
        payload = values.pop(field, None)
        if not values:
            self.hashes.pop(key, None)
        return payload


async def test_registry_owns_in_memory_upsert_list_get_and_pop() -> None:
    registry = SandboxHttpServiceRegistryV2()

    assert await registry.upsert_payload("project-a", "service-a", '{"value":1}') is False
    assert await registry.upsert_payload("project-a", "service-a", '{"value":2}') is True
    assert await registry.list_payloads("project-a") == {"service-a": '{"value":2}'}
    assert await registry.get_payload("project-a", "service-a") == '{"value":2}'
    assert await registry.pop_payload("project-a", "service-a") == '{"value":2}'
    assert await registry.get_payload("project-a", "service-a") is None


async def test_registry_recovers_opaque_payloads_from_redis() -> None:
    redis_client = _FakeRedisClient()
    writer = SandboxHttpServiceRegistryV2(redis_client=redis_client)
    reader = SandboxHttpServiceRegistryV2(redis_client=redis_client)

    assert await writer.upsert_payload("project-a", "service-a", '{"value":1}') is False

    assert await reader.list_payloads("project-a") == {"service-a": '{"value":1}'}
    assert await reader.get_payload("project-a", "service-a") == '{"value":1}'
    assert await reader.pop_payload("project-a", "service-a") == '{"value":1}'
    assert await writer.get_payload("project-a", "service-a") is None


async def test_registry_uses_memory_when_redis_fails(caplog: pytest.LogCaptureFixture) -> None:
    class _FailingRedisClient(_FakeRedisClient):
        async def hget(self, key: str, field: str) -> str | None:
            _ = key, field
            raise RuntimeError("sensitive redis detail")

    registry = SandboxHttpServiceRegistryV2(redis_client=_FailingRedisClient())

    assert await registry.upsert_payload("project-a", "service-a", '{"value":1}') is False
    assert await registry.get_payload("project-a", "service-a") == '{"value":1}'
    assert "RuntimeError" in caplog.text
    assert "sensitive redis detail" not in caplog.text


async def test_registry_is_provided_by_the_pinned_generation_and_disposed_with_it() -> None:
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    publication = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=93,
        version=93,
    )
    assert publication.accepted is True
    registry: SandboxHttpServiceRegistryV2 | None = None
    try:
        async with await host.acquire() as generation:
            resolved = generation.resolve(
                SANDBOX_HTTP_SERVICE_REGISTRY_SERVICE_V2,
                ScopeV2(kind=ScopeKindV2.ROOT),
            )
            assert isinstance(resolved, SandboxHttpServiceRegistryV2)
            registry = resolved
            _ = await registry.upsert_payload("project-a", "service-a", '{"value":1}')
    finally:
        await host.close()

    assert registry is not None
    with pytest.raises(RuntimeV2Error) as error:
        await registry.get_payload("project-a", "service-a")
    assert error.value.code == "sandbox_http_service_registry_disposed"


def test_registry_is_an_explicit_profile_entry() -> None:
    document = load_profile_document_v2(_PROFILE_PATH)
    entry = next(
        item
        for item in document.entries
        if item.module_ref == SANDBOX_HTTP_SERVICE_REGISTRY_MODULE_V2
    )

    assert entry.enabled is True
    assert entry.config == {"strategy": "generation-owned-registry"}
    assert entry.inject == {}


def test_project_sandbox_router_has_no_private_registry_or_container_redis_fallback() -> None:
    source = (
        _ROOT / "src/infrastructure/adapters/primary/web/routers/project_sandbox.py"
    ).read_text(encoding="utf-8")

    assert "get_http_service_redis_client" not in source
    assert "_http_service_registry:" not in source
    assert "_http_service_registry_lock" not in source
    assert "app.state.container" not in source
