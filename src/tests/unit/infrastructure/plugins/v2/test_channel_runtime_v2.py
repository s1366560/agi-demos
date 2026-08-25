"""V2 lifecycle coverage for the process channel connection runtime."""

from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from dataclasses import dataclass, field, replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.channel_adapters import (
    CHANNEL_ADAPTER_CATALOG_MODULE_V2,
    FEISHU_CHANNEL_ADAPTER_MODULE_V2,
    ChannelAdapterBuildContextV2,
    ChannelAdapterMetadataV2,
    ChannelAdapterResolverProtocolV2,
)
from src.infrastructure.plugins.v2.channel_runtime import (
    CHANNEL_RUNTIME_ADAPTERS_INJECT_V2,
    CHANNEL_RUNTIME_MODULE_V2,
    CHANNEL_RUNTIME_SERVICE_V2,
    CHANNEL_RUNTIME_SESSIONS_INJECT_V2,
    ChannelRuntimeConfigV2,
    ChannelRuntimeManagerV2,
    ChannelRuntimeServiceProtocolV2,
    ChannelRuntimeServiceV2,
    UnavailableChannelRuntimeServiceV2,
)
from src.infrastructure.plugins.v2.composer import compose_profile_v2, load_profile_document_v2
from src.infrastructure.plugins.v2.protocol import parse_plugin_manifest_v2
from src.infrastructure.plugins.v2.runtime import LoaderV2, RuntimeV2Error

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[6]
_PROFILE_PATH = _ROOT / "config/plugin-profiles/memstack-default.v2.yaml"
_MANIFEST_PATH = _ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json"


@asynccontextmanager
async def _session_factory() -> Any:
    yield object()


@dataclass(frozen=True, kw_only=True)
class _Sessions:
    factory: Any = _session_factory


@dataclass(frozen=True, kw_only=True)
class _Resolver:
    name: str

    def metadata(self, channel_type: str) -> ChannelAdapterMetadataV2 | None:
        return ChannelAdapterMetadataV2(
            channel_type=channel_type,
            config_schema={},
            config_ui_hints={},
            defaults={},
            secret_paths=(),
            source_id=self.name,
        )

    def list_metadata(self) -> dict[str, ChannelAdapterMetadataV2]:
        metadata = self.metadata(self.name)
        assert metadata is not None
        return {self.name: metadata}

    async def build(self, context: ChannelAdapterBuildContextV2) -> object:
        return SimpleNamespace(resolver=self.name, context=context)


@dataclass(kw_only=True)
class _FakeConnectionManager:
    message_router: Any
    session_factory: Any
    fail_start: bool = False
    fail_preflight_for: str | None = None
    fail_rebind: bool = False
    cancel_rebind: bool = False
    connections: dict[str, object] = field(default_factory=dict)
    started_with: list[str] = field(default_factory=list)
    preflighted_with: list[str] = field(default_factory=list)
    rebound_with: list[str] = field(default_factory=list)
    shutdown_count: int = 0

    async def _resolver_name(self, lease_factory: Any) -> str:
        lease = await lease_factory()
        try:
            assert isinstance(lease.resolver, ChannelAdapterResolverProtocolV2)
            return lease.resolver.name
        finally:
            await lease.release()

    async def start_all(
        self,
        _session_factory: Any = None,
        *,
        resolver_lease_factory: Any,
        strict: bool,
    ) -> int:
        assert strict is True
        name = await self._resolver_name(resolver_lease_factory)
        self.started_with.append(name)
        if self.fail_start:
            raise RuntimeError("channel startup unavailable")
        return 1

    async def preflight_all(self, *, resolver_lease_factory: Any) -> int:
        name = await self._resolver_name(resolver_lease_factory)
        self.preflighted_with.append(name)
        if name == self.fail_preflight_for:
            raise RuntimeError("candidate adapter invalid")
        return 1

    async def rebind_all(self, *, resolver_lease_factory: Any) -> int:
        name = await self._resolver_name(resolver_lease_factory)
        self.rebound_with.append(name)
        if self.cancel_rebind:
            raise asyncio.CancelledError
        if self.fail_rebind:
            raise RuntimeError("candidate rebind unavailable")
        return 1

    async def add_connection(
        self,
        config: object,
        *,
        resolver_lease_factory: Any,
    ) -> object:
        name = await self._resolver_name(resolver_lease_factory)
        return SimpleNamespace(config=config, resolver=name)

    async def restart_connection(
        self,
        _config_id: str,
        *,
        resolver_lease_factory: Any,
    ) -> bool:
        _ = await self._resolver_name(resolver_lease_factory)
        return True

    async def remove_connection(self, _config_id: str) -> bool:
        return True

    async def shutdown_all(self) -> None:
        self.shutdown_count += 1

    def get_status(self, _config_id: str) -> dict[str, object] | None:
        return None

    def get_all_status(self) -> list[dict[str, object]]:
        return []


def _manager_factory(
    created: list[_FakeConnectionManager],
    *,
    fail_start: bool = False,
    fail_preflight_for: str | None = None,
    fail_rebind: bool = False,
    cancel_rebind: bool = False,
) -> Any:
    def build(*, message_router: Any, session_factory: Any) -> _FakeConnectionManager:
        manager = _FakeConnectionManager(
            message_router=message_router,
            session_factory=session_factory,
            fail_start=fail_start,
            fail_preflight_for=fail_preflight_for,
            fail_rebind=fail_rebind,
            cancel_rebind=cancel_rebind,
        )
        created.append(manager)
        return manager

    return build


async def test_initial_generation_starts_nonempty_runtime_without_process_host() -> None:
    created: list[_FakeConnectionManager] = []
    runtime = ChannelRuntimeManagerV2(manager_factory=_manager_factory(created))

    service = await runtime.acquire_generation(
        sessions=_Sessions(),
        adapters=_Resolver(name="initial"),
        config=ChannelRuntimeConfigV2(strict_startup=True),
    )

    assert isinstance(service, ChannelRuntimeServiceV2)
    assert runtime.generation_references == 1
    assert runtime.connection_leases == 0
    assert len(created) == 1
    assert created[0].started_with == ["initial"]

    await runtime.release_generation(service.generation_token)
    assert created[0].shutdown_count == 1
    assert runtime.generation_references == 0


async def test_candidate_is_preflighted_and_rebound_only_when_old_generation_releases() -> None:
    created: list[_FakeConnectionManager] = []
    runtime = ChannelRuntimeManagerV2(manager_factory=_manager_factory(created))
    first = await runtime.acquire_generation(
        sessions=_Sessions(),
        adapters=_Resolver(name="first"),
        config=ChannelRuntimeConfigV2(strict_startup=True),
    )
    candidate = await runtime.acquire_generation(
        sessions=_Sessions(),
        adapters=_Resolver(name="candidate"),
        config=ChannelRuntimeConfigV2(strict_startup=True),
    )

    assert created[0].preflighted_with == ["candidate"]
    assert created[0].rebound_with == []
    assert runtime.active_generation_token == first.generation_token

    await runtime.release_generation(first.generation_token)

    assert created[0].rebound_with == ["candidate"]
    assert runtime.active_generation_token == candidate.generation_token
    await runtime.release_generation(candidate.generation_token)


async def test_failed_candidate_cleanup_preserves_active_manager_and_connections() -> None:
    created: list[_FakeConnectionManager] = []
    runtime = ChannelRuntimeManagerV2(
        manager_factory=_manager_factory(created, fail_preflight_for="broken")
    )
    active = await runtime.acquire_generation(
        sessions=_Sessions(),
        adapters=_Resolver(name="active"),
        config=ChannelRuntimeConfigV2(strict_startup=True),
    )

    with pytest.raises(RuntimeError, match="candidate adapter invalid"):
        await runtime.acquire_generation(
            sessions=_Sessions(),
            adapters=_Resolver(name="broken"),
            config=ChannelRuntimeConfigV2(strict_startup=True),
        )

    assert runtime.generation_references == 1
    assert runtime.active_generation_token == active.generation_token
    assert created[0].rebound_with == []
    assert created[0].shutdown_count == 0
    await runtime.release_generation(active.generation_token)


async def test_rebind_failure_retains_old_resolver_until_connection_releases() -> None:
    created: list[_FakeConnectionManager] = []
    runtime = ChannelRuntimeManagerV2(manager_factory=_manager_factory(created, fail_rebind=True))
    active = await runtime.acquire_generation(
        sessions=_Sessions(),
        adapters=_Resolver(name="active"),
        config=ChannelRuntimeConfigV2(strict_startup=True),
    )
    active_connection = await runtime.acquire_connection(active.generation_token)
    candidate = await runtime.acquire_generation(
        sessions=_Sessions(),
        adapters=_Resolver(name="candidate"),
        config=ChannelRuntimeConfigV2(strict_startup=True),
    )

    await runtime.release_generation(active.generation_token)

    assert created[0].rebound_with == ["candidate"]
    assert runtime.active_generation_token == candidate.generation_token
    assert runtime.generation_references == 1
    assert runtime.connection_leases == 1
    assert active_connection.resolver.name == "active"

    await active_connection.release()
    assert runtime.connection_leases == 0
    assert set(runtime._registrations) == {candidate.generation_token}
    await runtime.release_generation(candidate.generation_token)


async def test_rebind_cancellation_finishes_generation_retirement() -> None:
    created: list[_FakeConnectionManager] = []
    runtime = ChannelRuntimeManagerV2(manager_factory=_manager_factory(created, cancel_rebind=True))
    active = await runtime.acquire_generation(
        sessions=_Sessions(),
        adapters=_Resolver(name="active"),
        config=ChannelRuntimeConfigV2(strict_startup=True),
    )
    candidate = await runtime.acquire_generation(
        sessions=_Sessions(),
        adapters=_Resolver(name="candidate"),
        config=ChannelRuntimeConfigV2(strict_startup=True),
    )

    with pytest.raises(asyncio.CancelledError):
        await runtime.release_generation(active.generation_token)

    assert runtime.active_generation_token == candidate.generation_token
    assert runtime.generation_references == 1
    await runtime.release_generation(candidate.generation_token)


async def test_initial_start_failure_cleans_manager_and_generation_registration() -> None:
    created: list[_FakeConnectionManager] = []
    runtime = ChannelRuntimeManagerV2(manager_factory=_manager_factory(created, fail_start=True))

    with pytest.raises(RuntimeError, match="channel startup unavailable"):
        await runtime.acquire_generation(
            sessions=_Sessions(),
            adapters=_Resolver(name="broken-initial"),
            config=ChannelRuntimeConfigV2(strict_startup=True),
        )

    assert runtime.generation_references == 0
    assert runtime.active_generation_token is None
    assert runtime.manager is None
    assert created[0].shutdown_count == 1


async def test_generation_service_uses_its_exact_candidate_resolver() -> None:
    created: list[_FakeConnectionManager] = []
    runtime = ChannelRuntimeManagerV2(manager_factory=_manager_factory(created))
    first = await runtime.acquire_generation(
        sessions=_Sessions(),
        adapters=_Resolver(name="first"),
        config=ChannelRuntimeConfigV2(strict_startup=True),
    )
    candidate = await runtime.acquire_generation(
        sessions=_Sessions(),
        adapters=_Resolver(name="candidate"),
        config=ChannelRuntimeConfigV2(strict_startup=True),
    )

    connection = await candidate.add_connection(object())

    assert connection.resolver == "candidate"
    assert runtime.connection_leases == 0
    await runtime.release_generation(candidate.generation_token)
    await runtime.release_generation(first.generation_token)


def test_unavailable_channel_runtime_satisfies_protocol_and_fails_closed() -> None:
    service = UnavailableChannelRuntimeServiceV2()

    assert isinstance(service, ChannelRuntimeServiceProtocolV2)
    with pytest.raises(RuntimeV2Error) as error:
        service.get_all_status()

    assert error.value.code == "channel_runtime_manager_unavailable"


async def test_channel_runtime_rejects_missing_adapter_resolver_without_fallback() -> None:
    document = load_profile_document_v2(_PROFILE_PATH)
    disabled = replace(
        document,
        entries=tuple(
            replace(entry, enabled=False)
            if entry.module_ref
            in {
                CHANNEL_ADAPTER_CATALOG_MODULE_V2,
                FEISHU_CHANNEL_ADAPTER_MODULE_V2,
            }
            else entry
            for entry in document.entries
        ),
    )
    manifest = parse_plugin_manifest_v2(json.loads(_MANIFEST_PATH.read_text(encoding="utf-8")))
    snapshot = compose_profile_v2(disabled, {manifest.plugin_id: manifest}, generation=311)

    with pytest.raises(RuntimeV2Error) as error:
        await LoaderV2(builtin_runtime_definitions_v2()).stage(snapshot)

    assert error.value.code == "missing_inject_provider"
    assert "builtin-channel-runtime" in str(error.value)


def test_channel_runtime_contract_and_static_authority_retirement_are_explicit() -> None:
    profile = load_profile_document_v2(_PROFILE_PATH)
    entry = next(item for item in profile.entries if item.module_ref == CHANNEL_RUNTIME_MODULE_V2)
    manifest = parse_plugin_manifest_v2(json.loads(_MANIFEST_PATH.read_text(encoding="utf-8")))
    module = next(item for item in manifest.modules if item.module_ref == CHANNEL_RUNTIME_MODULE_V2)
    main_source = (_ROOT / "src/infrastructure/adapters/primary/web/main.py").read_text(
        encoding="utf-8"
    )
    startup_exports = (
        _ROOT / "src/infrastructure/adapters/primary/web/startup/__init__.py"
    ).read_text(encoding="utf-8")
    router_source = (
        _ROOT / "src/infrastructure/adapters/primary/web/routers/channels.py"
    ).read_text(encoding="utf-8")
    message_router_source = (
        _ROOT / "src/application/services/channels/channel_message_router.py"
    ).read_text(encoding="utf-8")

    assert entry.inject == {
        CHANNEL_RUNTIME_ADAPTERS_INJECT_V2: "service:channel-adapter-resolver",
        CHANNEL_RUNTIME_SESSIONS_INJECT_V2: "service:persistence.async-session-factory",
    }
    assert tuple(item.service for item in module.contract.services.provides) == (
        CHANNEL_RUNTIME_SERVICE_V2,
    )
    assert entry.restart_policy.value == "process-boundary"
    assert "channel_runtime_manager=channel_runtime_manager" in main_source
    assert "initialize_channel_manager" not in main_source
    assert "shutdown_channel_manager" not in main_source
    assert "get_channel_manager" not in startup_exports
    assert "get_channel_manager" not in router_source
    assert "get_channel_manager" not in message_router_source
    assert not (_ROOT / "src/infrastructure/adapters/primary/web/startup/channels.py").exists()
