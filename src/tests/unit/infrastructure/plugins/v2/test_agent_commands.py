"""Generation-owned slash-command catalog coverage for the V2 Agent spine."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, cast

import pytest

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.adapters.primary.web.routers.agent import commands as command_routes
from src.infrastructure.agent.commands.builtins import register_builtin_commands
from src.infrastructure.agent.commands.registry import CommandRegistry
from src.infrastructure.plugins.v2.agent_commands import (
    AGENT_COMMAND_CATALOG_MODULE_V2,
    AGENT_COMMAND_CATALOG_SERVICE_V2,
    AGENT_COMMAND_CONTRIBUTION_MODULE_V2,
    AgentCommandCatalogV2,
    PinnedCommandInterceptorV2,
    current_agent_command_catalog_v2,
    current_generation_agent_command_catalog_v2,
)
from src.infrastructure.plugins.v2.boundary import pin_generation_v2, pin_operation_context_v2
from src.infrastructure.plugins.v2.builtin_modules import (
    RUNTIME_BOUNDARY_MODULE_V2,
    builtin_runtime_definitions_v2,
)
from src.infrastructure.plugins.v2.composer import compose_profile_v2, load_profile_document_v2
from src.infrastructure.plugins.v2.protocol import parse_plugin_manifest_v2
from src.infrastructure.plugins.v2.runtime import GenerationManagerV2, LoaderV2, RuntimeV2Error
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2

if TYPE_CHECKING:
    from src.infrastructure.adapters.secondary.persistence.models import User

_ROOT = Path(__file__).resolve().parents[6]
_PROFILE_PATH = _ROOT / "config/plugin-profiles/memstack-default.v2.yaml"
_MANIFEST_PATH = _ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json"


def _builtin_definitions():
    registry = CommandRegistry()
    register_builtin_commands(registry)
    return tuple(registry.list_commands(include_hidden=True))


def _snapshot(*, generation: int, contribution_enabled: bool = True):
    manifest = parse_plugin_manifest_v2(json.loads(_MANIFEST_PATH.read_text(encoding="utf-8")))
    document = load_profile_document_v2(_PROFILE_PATH)
    selected_modules = {
        RUNTIME_BOUNDARY_MODULE_V2,
        AGENT_COMMAND_CATALOG_MODULE_V2,
        AGENT_COMMAND_CONTRIBUTION_MODULE_V2,
    }
    entries = tuple(
        replace(
            entry,
            enabled=(
                contribution_enabled
                if entry.module_ref == AGENT_COMMAND_CONTRIBUTION_MODULE_V2
                else entry.enabled
            ),
        )
        for entry in document.entries
        if entry.module_ref in selected_modules
    )
    return compose_profile_v2(
        replace(document, entries=entries),
        {manifest.plugin_id: manifest},
        generation=generation,
    )


@pytest.mark.unit
async def test_command_contribution_disposer_removes_exact_source() -> None:
    catalog = AgentCommandCatalogV2()
    dispose = catalog.register("builtin-commands", _builtin_definitions())

    assert "help" in {command.name for command in catalog.list_commands()}

    await dispose()

    assert catalog.list_commands() == []


@pytest.mark.unit
def test_command_catalog_rejects_duplicate_names_across_sources() -> None:
    catalog = AgentCommandCatalogV2()
    definitions = _builtin_definitions()
    _ = catalog.register("first", definitions)

    with pytest.raises(RuntimeV2Error) as error:
        catalog.register("second", definitions)

    assert error.value.code == "agent_command_contribution_conflict"


@pytest.mark.unit
def test_pinned_command_interceptor_requires_operation_without_static_fallback() -> None:
    interceptor = PinnedCommandInterceptorV2()

    with pytest.raises(RuntimeV2Error) as error:
        interceptor.is_command("hello")

    assert error.value.code == "operation_context_not_pinned"


@pytest.mark.unit
async def test_default_generation_resolves_builtin_command_contribution() -> None:
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=1,
        version=1,
    )

    try:
        async with pin_operation_context_v2(
            host,
            operation_id="agent-command-consumer",
            scope=ScopeV2(kind=ScopeKindV2.ROOT),
        ):
            catalog = current_agent_command_catalog_v2()
            command_names = {command.name for command in catalog.list_commands()}
            assert PinnedCommandInterceptorV2().is_command("/help") is True
    finally:
        await host.close()

    assert "help" in command_names
    assert "commands" in command_names


@pytest.mark.unit
async def test_http_command_listing_uses_generation_without_operation_fallback() -> None:
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=1,
        version=1,
    )

    try:
        async with pin_generation_v2(host):
            catalog = current_generation_agent_command_catalog_v2()
            expected_total = len(catalog.list_commands())
            response = await command_routes.list_commands(
                category=None,
                scope=None,
                current_user=cast("User", object()),
            )
    finally:
        await host.close()

    assert response.total == expected_total
    assert {command.name for command in response.commands} >= {"commands", "help"}


@pytest.mark.unit
def test_command_provider_and_builtin_source_are_explicit_profile_entries() -> None:
    document = load_profile_document_v2(_PROFILE_PATH)
    modules = {entry.module_ref for entry in document.entries if entry.enabled}

    assert AGENT_COMMAND_CATALOG_MODULE_V2 in modules
    assert AGENT_COMMAND_CONTRIBUTION_MODULE_V2 in modules


@pytest.mark.unit
async def test_disabling_builtin_command_contribution_removes_commands_without_fallback() -> None:
    generation = await LoaderV2(builtin_runtime_definitions_v2()).stage(
        _snapshot(generation=2, contribution_enabled=False)
    )
    manager = GenerationManagerV2()
    await manager.publish(generation)

    try:
        async with pin_operation_context_v2(
            manager,
            operation_id="disabled-command-contribution",
            scope=ScopeV2(kind=ScopeKindV2.ROOT),
        ) as operation:
            catalog = operation.require(AGENT_COMMAND_CATALOG_SERVICE_V2)
            assert isinstance(catalog, AgentCommandCatalogV2)
            assert catalog.list_commands() == []
    finally:
        await manager.close()


@pytest.mark.unit
def test_production_consumers_do_not_build_static_builtin_registries() -> None:
    react_source = (_ROOT / "src/infrastructure/agent/core/react_agent.py").read_text(
        encoding="utf-8"
    )
    route_source = (
        _ROOT / "src/infrastructure/adapters/primary/web/routers/agent/commands.py"
    ).read_text(encoding="utf-8")

    assert "register_builtin_commands" not in react_source
    assert "CommandRegistry" not in react_source
    assert "register_builtin_commands" not in route_source
    assert "_get_command_registry" not in route_source
