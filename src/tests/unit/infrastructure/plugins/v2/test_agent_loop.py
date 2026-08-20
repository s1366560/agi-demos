"""Real Provider/Consumer coverage for the generation-scoped agent-loop seam."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.agent.processor.factory import _default_loop_resolver
from src.infrastructure.plugins.v2.agent_loop import (
    AGENT_LOOP_RESOLVER_SERVICE_V2,
    BuiltinAgentLoopResolverV2,
)
from src.infrastructure.plugins.v2.boundary import pin_operation_context_v2
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2

_ROOT = Path(__file__).resolve().parents[6]


@pytest.mark.unit
async def test_processor_factory_consumes_generation_scoped_agent_loop_provider() -> None:
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    await host.bootstrap(
        profile_path=_ROOT / "config/plugin-profiles/memstack-default.v2.yaml",
        manifest_paths=(_ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json",),
        generation=1,
        version=1,
    )

    async with pin_operation_context_v2(
        host,
        operation_id="agent-loop-consumer",
        scope=ScopeV2(kind=ScopeKindV2.ROOT),
    ) as operation:
        resolver = _default_loop_resolver()
        assert isinstance(resolver, BuiltinAgentLoopResolverV2)
        assert operation.require(AGENT_LOOP_RESOLVER_SERVICE_V2) is resolver
        selection = resolver.resolve("deepseek", "deepseek-chat")
        assert selection.loop_id == "builtin-react"
        assert selection.plugin_id == "memstack-kernel"
        assert selection.scope == "builtin"

    await host.close()


@pytest.mark.unit
async def test_agent_loop_provider_disappears_when_generation_unloads() -> None:
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    await host.bootstrap(
        profile_path=_ROOT / "config/plugin-profiles/memstack-default.v2.yaml",
        manifest_paths=(_ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json",),
        generation=1,
        version=1,
    )
    async with await host.acquire() as generation:
        assert isinstance(
            generation.resolve(
                AGENT_LOOP_RESOLVER_SERVICE_V2,
                ScopeV2(kind=ScopeKindV2.ROOT),
            ),
            BuiltinAgentLoopResolverV2,
        )

    await host.close()

    with pytest.raises(RuntimeError, match="generation is disposed"):
        generation.resolve(
            AGENT_LOOP_RESOLVER_SERVICE_V2,
            ScopeV2(kind=ScopeKindV2.ROOT),
        )
