"""Provider/Consumer coverage for generation-scoped agent definitions."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.agent.core.react_agent import ReActAgent
from src.infrastructure.plugins.v2.agent_definition import (
    AGENT_DEFINITION_RESOLVER_SERVICE_V2,
    AgentDefinitionResolverV2,
)
from src.infrastructure.plugins.v2.boundary import pin_operation_context_v2
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2

_ROOT = Path(__file__).resolve().parents[6]


@pytest.mark.unit
async def test_react_agent_consumes_generation_agent_definition_provider() -> None:
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    await host.bootstrap(
        profile_path=_ROOT / "config/plugin-profiles/memstack-default.v2.yaml",
        manifest_paths=(_ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json",),
        generation=1,
        version=1,
    )
    selected = SimpleNamespace(id="agent-v2")
    agent = ReActAgent(model="test-model", tools={})

    async with pin_operation_context_v2(
        host,
        operation_id="agent-definition-consumer",
        scope=ScopeV2(kind=ScopeKindV2.ROOT),
    ) as operation:
        resolver = operation.require(AGENT_DEFINITION_RESOLVER_SERVICE_V2)
        assert isinstance(resolver, AgentDefinitionResolverV2)
        with patch.object(
            AgentDefinitionResolverV2,
            "resolve",
            new_callable=AsyncMock,
            return_value=selected,
        ) as resolve:
            result = await agent._load_selected_agent(
                agent_id="agent-v2",
                tenant_id="tenant-a",
                project_id="project-a",
            )

    assert result is selected
    resolve.assert_awaited_once()
    assert resolve.await_args.kwargs["loader"] == agent._load_selected_agent_native
    await host.close()


@pytest.mark.unit
async def test_agent_definition_provider_disappears_when_generation_unloads() -> None:
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
                AGENT_DEFINITION_RESOLVER_SERVICE_V2,
                ScopeV2(kind=ScopeKindV2.ROOT),
            ),
            AgentDefinitionResolverV2,
        )

    await host.close()

    with pytest.raises(RuntimeError, match="generation is disposed"):
        generation.resolve(
            AGENT_DEFINITION_RESOLVER_SERVICE_V2,
            ScopeV2(kind=ScopeKindV2.ROOT),
        )
