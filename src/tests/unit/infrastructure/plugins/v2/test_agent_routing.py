"""Generation-owned agent-routing coverage for channel turns."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest

from src.domain.model.agent.agent_binding import AgentBinding
from src.domain.model.agent.agent_definition import Agent
from src.domain.model.agent.subagent import AgentTrigger
from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.agent.sisyphus.builtin_agent import BUILTIN_SISYPHUS_ID
from src.infrastructure.plugins.v2.agent_definition import (
    AGENT_DEFINITION_CONTRIBUTION_MODULE_V2,
    AgentDefinitionCatalogV2,
    AgentDefinitionResolverV2,
)
from src.infrastructure.plugins.v2.agent_routing import (
    AGENT_ROUTE_RESOLVER_SERVICE_V2,
    AGENT_ROUTING_MODULE_V2,
    AgentRouteResolverV2,
)
from src.infrastructure.plugins.v2.boundary import (
    OPERATION_DB_SESSION_SERVICE_V2,
    pin_operation_context_v2,
)
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.composer import compose_profile_v2, load_profile_document_v2
from src.infrastructure.plugins.v2.protocol import parse_plugin_manifest_v2
from src.infrastructure.plugins.v2.runtime import GenerationManagerV2, LoaderV2, RuntimeV2Error

_ROOT = Path(__file__).resolve().parents[6]
_PROFILE_PATH = _ROOT / "config/plugin-profiles/memstack-default.v2.yaml"
_MANIFEST_PATH = _ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json"
_CHANNEL_ROUTER_PATH = _ROOT / "src/application/services/channels/channel_message_router.py"


def _agent(
    agent_id: str,
    *,
    tenant_id: str = "tenant-a",
    project_id: str | None = None,
    enabled: bool = True,
) -> Agent:
    return Agent(
        id=agent_id,
        tenant_id=tenant_id,
        project_id=project_id,
        name=agent_id,
        display_name=agent_id,
        system_prompt="Route this channel turn.",
        trigger=AgentTrigger(description="Use for channel routing"),
        enabled=enabled,
    )


def _operation(*, tenant_id: str = "tenant-a", project_id: str = "project-a") -> Mock:
    operation = Mock()
    operation.context.scope = ScopeV2(
        kind=ScopeKindV2.SESSION,
        tenant_id=tenant_id,
        project_id=project_id,
        session_id="conversation-a",
    )
    operation.require.return_value = object()
    return operation


@pytest.mark.unit
async def test_no_binding_resolves_explicit_profile_default_definition() -> None:
    catalog = AgentDefinitionCatalogV2()
    default_agent = _agent(BUILTIN_SISYPHUS_ID)
    _ = catalog.register(BUILTIN_SISYPHUS_ID, lambda _tenant, _project: default_agent)
    definition_resolver = AgentDefinitionResolverV2(strategy="explicit-id", catalog=catalog)
    binding_repository = SimpleNamespace(resolve_binding=AsyncMock(return_value=None))
    agent_registry = SimpleNamespace(get_by_id=AsyncMock())
    resolver = AgentRouteResolverV2(
        default_agent_id=BUILTIN_SISYPHUS_ID,
        definition_resolver=definition_resolver,
        binding_repository_factory=lambda _db: binding_repository,
        agent_registry_factory=lambda _db: agent_registry,
    )
    operation = _operation()

    with patch(
        "src.infrastructure.plugins.v2.boundary.current_operation_context_v2",
        return_value=operation,
    ):
        result = await resolver.resolve(
            tenant_id="tenant-a",
            project_id="project-a",
            channel_type="feishu",
            channel_id="channel-a",
            account_id="account-a",
            peer_id="peer-a",
        )

    assert result.agent is default_agent
    assert result.agent_id == BUILTIN_SISYPHUS_ID
    assert result.binding_id is None
    assert result.source == "profile-default"
    agent_registry.get_by_id.assert_not_awaited()


@pytest.mark.unit
async def test_binding_and_custom_definition_share_generation_resolver() -> None:
    binding = AgentBinding(
        id="binding-a",
        tenant_id="tenant-a",
        agent_id="custom-agent",
        channel_type="feishu",
    )
    selected = _agent("custom-agent", project_id="project-a")
    binding_repository = SimpleNamespace(resolve_binding=AsyncMock(return_value=binding))
    agent_registry = SimpleNamespace(get_by_id=AsyncMock(return_value=selected))
    resolver = AgentRouteResolverV2(
        default_agent_id=BUILTIN_SISYPHUS_ID,
        definition_resolver=AgentDefinitionResolverV2(
            strategy="explicit-id",
            catalog=AgentDefinitionCatalogV2(),
        ),
        binding_repository_factory=lambda _db: binding_repository,
        agent_registry_factory=lambda _db: agent_registry,
    )
    operation = _operation()

    with patch(
        "src.infrastructure.plugins.v2.boundary.current_operation_context_v2",
        return_value=operation,
    ):
        result = await resolver.resolve(
            tenant_id="tenant-a",
            project_id="project-a",
            channel_type="feishu",
        )

    assert result.agent is selected
    assert result.agent_id == "custom-agent"
    assert result.binding_id == "binding-a"
    assert result.source == "binding"
    agent_registry.get_by_id.assert_awaited_once_with(
        agent_id="custom-agent",
        tenant_id="tenant-a",
        project_id="project-a",
    )


@pytest.mark.unit
@pytest.mark.parametrize(
    ("selected", "expected_code"),
    [
        (None, "agent_route_definition_not_found"),
        (_agent("disabled-agent", enabled=False), "agent_route_definition_disabled"),
    ],
)
async def test_invalid_bound_definition_fails_without_default_fallback(
    selected: Agent | None,
    expected_code: str,
) -> None:
    binding = AgentBinding(
        id="binding-a",
        tenant_id="tenant-a",
        agent_id="disabled-agent",
    )
    binding_repository = SimpleNamespace(resolve_binding=AsyncMock(return_value=binding))
    agent_registry = SimpleNamespace(get_by_id=AsyncMock(return_value=selected))
    resolver = AgentRouteResolverV2(
        default_agent_id=BUILTIN_SISYPHUS_ID,
        definition_resolver=AgentDefinitionResolverV2(
            strategy="explicit-id",
            catalog=AgentDefinitionCatalogV2(),
        ),
        binding_repository_factory=lambda _db: binding_repository,
        agent_registry_factory=lambda _db: agent_registry,
    )

    with (
        patch(
            "src.infrastructure.plugins.v2.boundary.current_operation_context_v2",
            return_value=_operation(),
        ),
        pytest.raises(RuntimeV2Error) as error,
    ):
        await resolver.resolve(tenant_id="tenant-a", project_id="project-a")

    assert error.value.code == expected_code


@pytest.mark.unit
async def test_operation_scope_mismatch_is_rejected_before_repository_access() -> None:
    binding_repository_factory = Mock()
    agent_registry_factory = Mock()
    resolver = AgentRouteResolverV2(
        default_agent_id=BUILTIN_SISYPHUS_ID,
        definition_resolver=AgentDefinitionResolverV2(
            strategy="explicit-id",
            catalog=AgentDefinitionCatalogV2(),
        ),
        binding_repository_factory=binding_repository_factory,
        agent_registry_factory=agent_registry_factory,
    )

    with (
        patch(
            "src.infrastructure.plugins.v2.boundary.current_operation_context_v2",
            return_value=_operation(tenant_id="tenant-b"),
        ),
        pytest.raises(RuntimeV2Error) as error,
    ):
        await resolver.resolve(tenant_id="tenant-a", project_id="project-a")

    assert error.value.code == "agent_route_scope_mismatch"
    binding_repository_factory.assert_not_called()
    agent_registry_factory.assert_not_called()


@pytest.mark.unit
def test_default_profile_declares_explicit_agent_routing_provider() -> None:
    document = load_profile_document_v2(_PROFILE_PATH)
    entries = [entry for entry in document.entries if entry.module_ref == AGENT_ROUTING_MODULE_V2]

    assert len(entries) == 1
    assert entries[0].config == {"default_agent_id": BUILTIN_SISYPHUS_ID}
    assert entries[0].inject == {"definition_resolver": "service:agent-definition-resolver"}


@pytest.mark.unit
def test_channel_production_path_has_no_static_binding_or_builtin_fallback() -> None:
    source = _CHANNEL_ROUTER_PATH.read_text(encoding="utf-8")

    assert "container.binding_router()" not in source
    assert "get_settings().multi_agent_enabled" not in source
    assert "falling back to default agent" not in source
    assert "build_builtin_sisyphus_agent" not in source


@pytest.mark.unit
async def test_disabling_profile_default_definition_removes_routing_capability() -> None:
    document = load_profile_document_v2(_PROFILE_PATH)
    disabled = replace(
        document,
        entries=tuple(
            replace(entry, enabled=False)
            if entry.module_ref == AGENT_DEFINITION_CONTRIBUTION_MODULE_V2
            and entry.config.get("agent_id") == BUILTIN_SISYPHUS_ID
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
    binding_repository = SimpleNamespace(resolve_binding=AsyncMock(return_value=None))
    agent_registry = SimpleNamespace(get_by_id=AsyncMock())

    with (
        patch(
            "src.infrastructure.plugins.v2.agent_routing._build_binding_repository_v2",
            return_value=binding_repository,
        ),
        patch(
            "src.infrastructure.plugins.v2.agent_routing._build_agent_registry_v2",
            return_value=agent_registry,
        ),
    ):
        generation = await LoaderV2(builtin_runtime_definitions_v2()).stage(snapshot)
        manager = GenerationManagerV2()
        await manager.publish(generation)
        try:
            async with pin_operation_context_v2(
                manager,
                operation_id="disabled-default-routing",
                scope=ScopeV2(
                    kind=ScopeKindV2.SESSION,
                    tenant_id="tenant-a",
                    project_id="project-a",
                    session_id="conversation-a",
                ),
                services={OPERATION_DB_SESSION_SERVICE_V2: object()},
            ) as operation:
                resolver = operation.require(AGENT_ROUTE_RESOLVER_SERVICE_V2)
                assert isinstance(resolver, AgentRouteResolverV2)
                with pytest.raises(RuntimeV2Error) as error:
                    await resolver.resolve(
                        tenant_id="tenant-a",
                        project_id="project-a",
                    )
        finally:
            await manager.close()

    assert error.value.code == "agent_route_definition_not_found"
    agent_registry.get_by_id.assert_not_awaited()
