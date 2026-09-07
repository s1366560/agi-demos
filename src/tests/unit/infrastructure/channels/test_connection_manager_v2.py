"""Generation resolver lease coverage for long-lived channel connections."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.channel_runtime import (
    CHANNEL_RUNTIME_SERVICE_V2,
    ChannelRuntimeManagerV2,
    ChannelRuntimeServiceV2,
)
from src.infrastructure.plugins.v2.runtime import FiberPhaseV2
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2

_ROOT = Path(__file__).resolve().parents[5]
_PROFILE_PATH = _ROOT / "config/plugin-profiles/memstack-default.v2.yaml"
_MANIFEST_PATH = _ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json"


@dataclass(kw_only=True)
class _ConnectionManager:
    message_router: Any
    session_factory: Any
    connections: dict[str, object] = field(default_factory=dict)
    start_resolvers: list[object] = field(default_factory=list)
    candidate_resolvers: list[object] = field(default_factory=list)
    rebound_resolvers: list[object] = field(default_factory=list)
    shutdown_count: int = 0

    async def _capture(self, lease_factory: Any, target: list[object]) -> None:
        lease = await lease_factory()
        target.append(lease.resolver)
        await lease.release()

    async def start_all(
        self,
        _session_factory: Any = None,
        *,
        resolver_lease_factory: Any,
        strict: bool,
    ) -> int:
        assert strict is True
        await self._capture(resolver_lease_factory, self.start_resolvers)
        return 0

    async def preflight_all(self, *, resolver_lease_factory: Any) -> int:
        await self._capture(resolver_lease_factory, self.candidate_resolvers)
        return 0

    async def rebind_all(self, *, resolver_lease_factory: Any) -> int:
        await self._capture(resolver_lease_factory, self.rebound_resolvers)
        return 0

    async def shutdown_all(self) -> None:
        self.shutdown_count += 1


@pytest.mark.unit
async def test_channel_runtime_rebinds_after_publish_without_leasing_its_own_generation() -> None:
    created: list[_ConnectionManager] = []

    def manager_factory(*, message_router: Any, session_factory: Any) -> _ConnectionManager:
        manager = _ConnectionManager(
            message_router=message_router,
            session_factory=session_factory,
        )
        created.append(manager)
        return manager

    runtime = ChannelRuntimeManagerV2(manager_factory=manager_factory)
    host = PlatformPluginRuntimeHostV2(
        builtin_runtime_definitions_v2(channel_runtime_manager=runtime)
    )
    first = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=1,
        version=1,
    )
    assert first.accepted
    previous = host.manager.current
    assert previous is not None
    first_service = previous.resolve(
        CHANNEL_RUNTIME_SERVICE_V2,
        ScopeV2(kind=ScopeKindV2.ROOT),
    )
    assert isinstance(first_service, ChannelRuntimeServiceV2)

    second = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=2,
        version=2,
    )

    assert second.accepted
    assert all(fiber.phase is FiberPhaseV2.DISPOSED for fiber in previous.fibers)
    current = host.manager.current
    assert current is not None
    current_service = current.resolve(
        CHANNEL_RUNTIME_SERVICE_V2,
        ScopeV2(kind=ScopeKindV2.ROOT),
    )
    assert isinstance(current_service, ChannelRuntimeServiceV2)
    assert current_service.generation_token != first_service.generation_token
    assert len(created) == 1
    assert len(created[0].start_resolvers) == 1
    assert len(created[0].candidate_resolvers) == 1
    assert created[0].rebound_resolvers == created[0].candidate_resolvers
    assert runtime.connection_leases == 0

    await host.close()
    assert created[0].shutdown_count == 1
