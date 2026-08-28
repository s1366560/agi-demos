"""Provider/Consumer coverage for generation-scoped agent definitions."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.agent.core.react_agent import ReActAgent
from src.infrastructure.agent.sisyphus.builtin_agent import BUILTIN_ALL_ACCESS_ID
from src.infrastructure.plugins.v2.agent_definition import (
    AGENT_DEFINITION_CONTRIBUTION_MODULE_V2,
    AGENT_DEFINITION_RESOLVER_SERVICE_V2,
    BUILTIN_AGENT_DEFINITION_IDS_V2,
    AgentDefinitionCatalogV2,
    AgentDefinitionResolverV2,
)
from src.infrastructure.plugins.v2.agent_persisted_definition import (
    AGENT_PERSISTED_DEFINITION_MODULE_V2,
    AGENT_PERSISTED_DEFINITION_SOURCE_V2,
)
from src.infrastructure.plugins.v2.boundary import (
    OPERATION_DB_SESSION_SERVICE_V2,
    pin_operation_context_v2,
)
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.composer import compose_profile_v2, load_profile_document_v2
from src.infrastructure.plugins.v2.protocol import parse_plugin_manifest_v2
from src.infrastructure.plugins.v2.runtime import GenerationManagerV2, LoaderV2, RuntimeV2Error
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2

_ROOT = Path(__file__).resolve().parents[6]
_PROFILE_PATH = _ROOT / "config/plugin-profiles/memstack-default.v2.yaml"
_MANIFEST_PATH = _ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json"
_STREAM_MIXIN_PATH = _ROOT / "src/infrastructure/agent/core/react_agent_stream_mixin.py"
_PROMPT_MIXIN_PATH = _ROOT / "src/infrastructure/agent/core/react_agent_prompt_mixin.py"


class _AlternativeAgentDefinitionResolver:
    def __init__(self, result: object) -> None:
        self.result = result
        self.calls: list[dict[str, object]] = []

    async def resolve(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        return self.result


@pytest.mark.unit
async def test_agent_definition_contribution_disposer_removes_exact_entry() -> None:
    catalog = AgentDefinitionCatalogV2()
    disposer = catalog.register(
        "agent-a",
        lambda tenant_id, project_id: SimpleNamespace(
            id="agent-a",
            tenant_id=tenant_id,
            project_id=project_id,
        ),
    )

    resolved = catalog.resolve(
        agent_id="agent-a",
        tenant_id="tenant-a",
        project_id="project-a",
    )
    assert resolved is not None
    assert isinstance(resolved, SimpleNamespace)
    assert resolved.id == "agent-a"

    await disposer()

    assert (
        catalog.resolve(
            agent_id="agent-a",
            tenant_id="tenant-a",
            project_id="project-a",
        )
        is None
    )


@pytest.mark.unit
async def test_agent_definition_provider_disposer_removes_dynamic_source() -> None:
    catalog = AgentDefinitionCatalogV2()
    provider = AsyncMock(return_value=SimpleNamespace(id="agent-a"))
    disposer = catalog.register_provider("persisted-agent-definitions", provider)

    resolved = await catalog.resolve_provider(
        agent_id="agent-a",
        tenant_id="tenant-a",
        project_id="project-a",
    )
    assert resolved is not None
    assert resolved.id == "agent-a"

    await disposer()

    assert (
        await catalog.resolve_provider(
            agent_id="agent-a",
            tenant_id="tenant-a",
            project_id="project-a",
        )
        is None
    )


@pytest.mark.unit
async def test_agent_definition_requires_pinned_v2_operation_without_native_fallback() -> None:
    agent = ReActAgent(model="test-model", tools={})

    with pytest.raises(RuntimeV2Error) as error:
        await agent._load_selected_agent(
            agent_id="agent-v2",
            tenant_id="tenant-a",
            project_id="project-a",
        )

    assert error.value.code == "operation_context_not_pinned"


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
        pytest.raises(RuntimeV2Error) as error,
    ):
        await agent._load_selected_agent(
            agent_id="agent-v2",
            tenant_id="tenant-a",
            project_id="project-a",
        )

    assert error.value.code == "missing_service"
    operation.require.assert_called_once_with(AGENT_DEFINITION_RESOLVER_SERVICE_V2)


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
    assert provider.calls == [
        {
            "agent_id": "agent-v2",
            "tenant_id": "tenant-a",
            "project_id": "project-a",
        }
    ]


@pytest.mark.unit
def test_prompt_mixin_has_no_native_agent_definition_loader() -> None:
    source = _PROMPT_MIXIN_PATH.read_text(encoding="utf-8")

    assert "_load_selected_agent_native" not in source
    assert "SqlAgentRegistryRepository" not in source


@pytest.mark.unit
async def test_stream_requires_upstream_agent_id_before_route_side_effects(monkeypatch) -> None:
    agent = ReActAgent(model="test-model", tools={})

    async def no_plan_events(_user_message: str, _conversation_id: str):
        if False:
            yield {}

    plan_detector = Mock(side_effect=no_plan_events)
    route_parser = Mock(return_value=(None, "hello"))
    route_decider = Mock(return_value=(object(), "route", "trace", {}, None, {"type": "route"}))
    skill_loader = AsyncMock()
    definition_loader = AsyncMock()
    monkeypatch.setattr(agent, "_stream_detect_plan_mode", plan_detector)
    monkeypatch.setattr(agent, "_stream_parse_forced_subagent", route_parser)
    monkeypatch.setattr(agent, "_stream_decide_route", route_decider)
    monkeypatch.setattr(agent, "_load_filesystem_skills", skill_loader)
    monkeypatch.setattr(agent, "_load_selected_agent", definition_loader)

    events = agent.stream(
        conversation_id="conversation-a",
        user_message="hello",
        project_id="project-a",
        user_id="user-a",
        tenant_id="tenant-a",
    )
    with pytest.raises(RuntimeV2Error) as error:
        await anext(events)

    assert error.value.code == "agent_id_not_resolved"
    plan_detector.assert_not_called()
    route_parser.assert_not_called()
    route_decider.assert_not_called()
    skill_loader.assert_not_awaited()
    definition_loader.assert_not_awaited()


@pytest.mark.unit
async def test_stream_rejects_explicit_missing_definition_without_builtin_fallback(
    monkeypatch,
) -> None:
    agent = ReActAgent(model="test-model", tools={})
    route_event = {"type": "route"}

    async def no_plan_events(_user_message: str, _conversation_id: str):
        if False:
            yield {}

    monkeypatch.setattr(agent, "_stream_detect_plan_mode", no_plan_events)
    monkeypatch.setattr(agent, "_stream_parse_forced_subagent", Mock(return_value=(None, "hello")))
    monkeypatch.setattr(
        agent,
        "_stream_decide_route",
        Mock(return_value=(object(), "route", "trace", {}, None, route_event)),
    )
    monkeypatch.setattr(agent, "_load_filesystem_skills", AsyncMock())
    monkeypatch.setattr(
        "src.infrastructure.agent.core.react_agent_stream_mixin."
        "_resolve_agent_capabilities_from_runtime_v2",
        AsyncMock(return_value=SimpleNamespace(skills=(), subagents=())),
    )
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
            agent_id="missing-agent",
        )
        assert await anext(events) == route_event
        with pytest.raises(RuntimeV2Error) as error:
            await anext(events)

    assert error.value.code == "agent_definition_not_found"
    builtin_fallback.assert_not_called()


@pytest.mark.unit
def test_react_agent_stream_source_has_no_hardcoded_default_agent() -> None:
    source = _STREAM_MIXIN_PATH.read_text(encoding="utf-8")

    assert "DEFAULT_GENERAL_AGENT_ID" not in source
    assert "resolved_agent_id = agent_id or" not in source


@pytest.mark.unit
async def test_react_agent_consumes_generation_agent_definition_provider() -> None:
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    await host.bootstrap(
        profile_path=_ROOT / "config/plugin-profiles/memstack-default.v2.yaml",
        manifest_paths=(_ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json",),
        generation=1,
        version=1,
    )
    agent = ReActAgent(model="test-model", tools={})

    async with pin_operation_context_v2(
        host,
        operation_id="agent-definition-consumer",
        scope=ScopeV2(kind=ScopeKindV2.ROOT),
    ):
        result = await agent._load_selected_agent(
            agent_id=BUILTIN_ALL_ACCESS_ID,
            tenant_id="tenant-a",
            project_id="project-a",
        )

    assert result is not None
    assert result.id == BUILTIN_ALL_ACCESS_ID
    assert result.tenant_id == "tenant-a"
    assert result.project_id == "project-a"
    await host.close()


@pytest.mark.unit
async def test_react_agent_resolves_persisted_definition_from_profile_provider() -> None:
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=1,
        version=1,
    )
    selected = SimpleNamespace(
        id="persisted-agent",
        tenant_id="tenant-a",
        project_id="project-a",
    )
    repository = SimpleNamespace(get_by_id=AsyncMock(return_value=selected))
    agent = ReActAgent(model="test-model", tools={})

    try:
        with patch(
            "src.infrastructure.plugins.v2.agent_persisted_definition._build_agent_registry_v2",
            return_value=repository,
        ):
            async with pin_operation_context_v2(
                host,
                operation_id="persisted-agent-definition-consumer",
                scope=ScopeV2(
                    kind=ScopeKindV2.SESSION,
                    tenant_id="tenant-a",
                    project_id="project-a",
                    session_id="conversation-a",
                ),
                services={OPERATION_DB_SESSION_SERVICE_V2: object()},
            ):
                result = await agent._load_selected_agent(
                    agent_id="persisted-agent",
                    tenant_id="tenant-a",
                    project_id="project-a",
                )
    finally:
        await host.close()

    assert result is selected
    repository.get_by_id.assert_awaited_once_with(
        agent_id="persisted-agent",
        tenant_id="tenant-a",
        project_id="project-a",
    )


@pytest.mark.unit
def test_profile_declares_persisted_definition_provider() -> None:
    document = load_profile_document_v2(_PROFILE_PATH)
    entries = [
        entry
        for entry in document.entries
        if entry.module_ref == AGENT_PERSISTED_DEFINITION_MODULE_V2
    ]

    assert len(entries) == 1
    assert entries[0].config == {
        "strategy": "operation-agent-registry",
        "source_id": AGENT_PERSISTED_DEFINITION_SOURCE_V2,
    }
    assert entries[0].inject == {"catalog": "service:agent-definition-catalog"}


@pytest.mark.unit
def test_every_builtin_agent_is_an_explicit_profile_entry() -> None:
    document = load_profile_document_v2(_PROFILE_PATH)
    declared = {
        entry.config["agent_id"]
        for entry in document.entries
        if entry.module_ref == AGENT_DEFINITION_CONTRIBUTION_MODULE_V2
    }

    assert declared == set(BUILTIN_AGENT_DEFINITION_IDS_V2)


@pytest.mark.unit
async def test_disabling_builtin_agent_entry_removes_capability_without_fallback() -> None:
    document = load_profile_document_v2(_PROFILE_PATH)
    disabled = replace(
        document,
        entries=tuple(
            replace(entry, enabled=False)
            if entry.module_ref == AGENT_DEFINITION_CONTRIBUTION_MODULE_V2
            and entry.config.get("agent_id") == BUILTIN_ALL_ACCESS_ID
            else entry
            for entry in document.entries
        ),
    )
    manifest = parse_plugin_manifest_v2(json.loads(_MANIFEST_PATH.read_text(encoding="utf-8")))
    snapshot = compose_profile_v2(
        disabled,
        {manifest.plugin_id: manifest},
        generation=2,
    )
    generation = await LoaderV2(builtin_runtime_definitions_v2()).stage(snapshot)
    manager = GenerationManagerV2()
    await manager.publish(generation)
    persisted_provider_factory = Mock()

    try:
        with patch(
            "src.infrastructure.plugins.v2.agent_persisted_definition._build_agent_registry_v2",
            persisted_provider_factory,
        ):
            async with pin_operation_context_v2(
                manager,
                operation_id="disabled-builtin-agent",
                scope=ScopeV2(
                    kind=ScopeKindV2.SESSION,
                    tenant_id="tenant-a",
                    project_id="project-a",
                    session_id="conversation-a",
                ),
                services={OPERATION_DB_SESSION_SERVICE_V2: object()},
            ) as operation:
                resolver = operation.require(AGENT_DEFINITION_RESOLVER_SERVICE_V2)
                assert isinstance(resolver, AgentDefinitionResolverV2)
                result = await resolver.resolve(
                    agent_id=BUILTIN_ALL_ACCESS_ID,
                    tenant_id="tenant-a",
                    project_id="project-a",
                )
    finally:
        await manager.close()

    assert result is None
    persisted_provider_factory.assert_not_called()


@pytest.mark.unit
async def test_disabling_persisted_provider_removes_custom_definitions() -> None:
    document = load_profile_document_v2(_PROFILE_PATH)
    disabled = replace(
        document,
        entries=tuple(
            replace(entry, enabled=False)
            if entry.module_ref == AGENT_PERSISTED_DEFINITION_MODULE_V2
            else entry
            for entry in document.entries
        ),
    )
    manifest = parse_plugin_manifest_v2(json.loads(_MANIFEST_PATH.read_text(encoding="utf-8")))
    snapshot = compose_profile_v2(
        disabled,
        {manifest.plugin_id: manifest},
        generation=3,
    )
    generation = await LoaderV2(builtin_runtime_definitions_v2()).stage(snapshot)
    manager = GenerationManagerV2()
    await manager.publish(generation)

    try:
        async with pin_operation_context_v2(
            manager,
            operation_id="disabled-persisted-agent-provider",
            scope=ScopeV2(
                kind=ScopeKindV2.SESSION,
                tenant_id="tenant-a",
                project_id="project-a",
                session_id="conversation-a",
            ),
            services={OPERATION_DB_SESSION_SERVICE_V2: object()},
        ) as operation:
            resolver = operation.require(AGENT_DEFINITION_RESOLVER_SERVICE_V2)
            assert isinstance(resolver, AgentDefinitionResolverV2)
            result = await resolver.resolve(
                agent_id="persisted-agent",
                tenant_id="tenant-a",
                project_id="project-a",
            )
    finally:
        await manager.close()

    assert result is None


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
