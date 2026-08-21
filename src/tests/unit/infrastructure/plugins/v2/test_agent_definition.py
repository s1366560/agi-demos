"""Provider/Consumer coverage for generation-scoped agent definitions."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.agent.core.react_agent import ReActAgent
from src.infrastructure.plugins.v2.agent_definition import (
    AGENT_DEFINITION_RESOLVER_SERVICE_V2,
    AgentDefinitionResolverV2,
)
from src.infrastructure.plugins.v2.boundary import pin_operation_context_v2
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.runtime import RuntimeV2Error
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2

_ROOT = Path(__file__).resolve().parents[6]


class _AlternativeAgentDefinitionResolver:
    def __init__(self, result: object) -> None:
        self.result = result
        self.calls: list[dict[str, object]] = []

    async def resolve(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        return self.result


@pytest.mark.unit
async def test_agent_definition_requires_pinned_v2_operation_without_native_fallback() -> None:
    agent = ReActAgent(model="test-model", tools={})

    with (
        patch.object(
            agent,
            "_load_selected_agent_native",
            new_callable=AsyncMock,
        ) as native_loader,
        pytest.raises(RuntimeV2Error) as error,
    ):
        await agent._load_selected_agent(
            agent_id="agent-v2",
            tenant_id="tenant-a",
            project_id="project-a",
        )

    assert error.value.code == "operation_context_not_pinned"
    native_loader.assert_not_awaited()


@pytest.mark.unit
async def test_agent_definition_propagates_missing_v2_service_without_native_fallback() -> None:
    agent = ReActAgent(model="test-model", tools={})
    operation = Mock()
    operation.require.side_effect = RuntimeV2Error(
        "missing_service",
        "agent definition resolver is unavailable",
    )

    with (
        patch(
            "src.infrastructure.plugins.v2.boundary.current_operation_context_v2",
            return_value=operation,
        ),
        patch.object(
            agent,
            "_load_selected_agent_native",
            new_callable=AsyncMock,
        ) as native_loader,
        pytest.raises(RuntimeV2Error) as error,
    ):
        await agent._load_selected_agent(
            agent_id="agent-v2",
            tenant_id="tenant-a",
            project_id="project-a",
        )

    assert error.value.code == "missing_service"
    operation.require.assert_called_once_with(AGENT_DEFINITION_RESOLVER_SERVICE_V2)
    native_loader.assert_not_awaited()


@pytest.mark.unit
async def test_agent_definition_accepts_structural_non_builtin_provider() -> None:
    selected = SimpleNamespace(id="agent-v2")
    provider = _AlternativeAgentDefinitionResolver(selected)
    operation = Mock()
    operation.require.return_value = provider
    agent = ReActAgent(model="test-model", tools={})

    with patch(
        "src.infrastructure.plugins.v2.boundary.current_operation_context_v2",
        return_value=operation,
    ):
        result = await agent._load_selected_agent(
            agent_id="agent-v2",
            tenant_id="tenant-a",
            project_id="project-a",
        )

    assert result is selected
    operation.require.assert_called_once_with(AGENT_DEFINITION_RESOLVER_SERVICE_V2)
    assert provider.calls[0]["loader"] == agent._load_selected_agent_native


@pytest.mark.unit
async def test_stream_rejects_missing_selected_agent_without_builtin_fallback(monkeypatch) -> None:
    agent = ReActAgent(model="test-model", tools={})
    route_event = {"type": "route"}

    async def no_plan_events(_user_message: str, _conversation_id: str):
        if False:
            yield {}

    monkeypatch.setattr(agent, "_stream_detect_plan_mode", no_plan_events)
    monkeypatch.setattr(
        agent,
        "_stream_parse_forced_subagent",
        Mock(return_value=(None, "hello")),
    )
    monkeypatch.setattr(
        agent,
        "_stream_decide_route",
        Mock(return_value=(object(), "route", "trace", {}, None, route_event)),
    )
    monkeypatch.setattr(agent, "_load_filesystem_skills", AsyncMock())
    monkeypatch.setattr(agent, "_load_selected_agent", AsyncMock(return_value=None))

    with patch(
        "src.infrastructure.agent.core.react_agent_stream_mixin.build_builtin_all_access_agent",
        side_effect=AssertionError("builtin fallback must not be called"),
        create=True,
    ) as builtin_fallback:
        events = agent.stream(
            conversation_id="conversation-a",
            user_message="hello",
            project_id="project-a",
            user_id="user-a",
            tenant_id="tenant-a",
        )
        assert await anext(events) == route_event
        with pytest.raises(RuntimeV2Error) as error:
            await anext(events)

    assert error.value.code == "agent_definition_not_found"
    builtin_fallback.assert_not_called()


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
