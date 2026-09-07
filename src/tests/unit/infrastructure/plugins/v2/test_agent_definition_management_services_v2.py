"""V2 persistence and application seams for Agent Definition management."""

from __future__ import annotations

import inspect
import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.agent.agent_definition import Agent
from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.adapters.primary.web.routers.agent.definitions_router import (
    create_definition,
    delete_definition,
    get_definition,
    list_definitions,
    set_definition_enabled,
    update_definition,
)
from src.infrastructure.plugins.v2.agent_definition_management_services import (
    AGENT_DEFINITION_MANAGEMENT_MODULE_V2,
    AGENT_DEFINITION_MANAGEMENT_REPOSITORIES_INJECT_V2,
    AGENT_DEFINITION_MANAGEMENT_SERVICE_V2,
    AGENT_DEFINITION_REPOSITORY_PROVIDER_MODULE_V2,
    AgentDefinitionManagementResolverV2,
    AgentDefinitionManagementServiceV2,
)
from src.infrastructure.plugins.v2.boundary import OPERATION_DB_SESSION_SERVICE_V2
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.composer import compose_profile_v2, load_profile_document_v2
from src.infrastructure.plugins.v2.protocol import parse_plugin_manifest_v2
from src.infrastructure.plugins.v2.runtime import LoaderV2, OperationContextV2, RuntimeV2Error
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[6]
_PROFILE_PATH = _ROOT / "config/plugin-profiles/memstack-default.v2.yaml"
_MANIFEST_PATH = _ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json"


def _agent() -> Agent:
    return Agent.create(
        tenant_id="tenant-a",
        name="worker-agent",
        display_name="Worker Agent",
        system_prompt="Work carefully.",
    )


async def test_resolver_builds_definition_management_from_exact_operation_session() -> None:
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    publication = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=1006,
        version=1006,
    )
    assert publication.accepted is True
    db = AsyncSession()
    try:
        async with (
            await host.acquire() as generation,
            OperationContextV2(
                generation=generation,
                operation_id="agent-definition-management",
                scope=ScopeV2(kind=ScopeKindV2.ROOT),
            ) as operation,
        ):
            _ = operation.provide(OPERATION_DB_SESSION_SERVICE_V2, db)
            resolver = operation.require(AGENT_DEFINITION_MANAGEMENT_SERVICE_V2)

            assert isinstance(resolver, AgentDefinitionManagementResolverV2)
            service = resolver.resolve(operation)
            assert isinstance(service, AgentDefinitionManagementServiceV2)
            assert getattr(service.registry, "_session", None) is db
            assert getattr(service.external_agents, "_session", None) is db
            assert service.db is db
    finally:
        await db.close()
        await host.close()


async def test_create_agent_checks_uniqueness_and_commits_operation_session() -> None:
    agent = _agent()
    registry = MagicMock()
    registry.get_by_name = AsyncMock(return_value=None)
    registry.create = AsyncMock(return_value=agent)
    db = SimpleNamespace(commit=AsyncMock())
    service = AgentDefinitionManagementServiceV2(
        db=cast(Any, db),
        registry=registry,
        external_agents=MagicMock(),
    )

    created = await service.create_agent(agent)

    assert created is agent
    registry.get_by_name.assert_awaited_once_with("tenant-a", "worker-agent")
    registry.create.assert_awaited_once_with(agent)
    db.commit.assert_awaited_once_with()


async def test_create_agent_rejects_duplicate_without_write_or_commit() -> None:
    agent = _agent()
    registry = MagicMock()
    registry.get_by_name = AsyncMock(return_value=SimpleNamespace(id="existing-agent"))
    registry.create = AsyncMock()
    db = SimpleNamespace(commit=AsyncMock())
    service = AgentDefinitionManagementServiceV2(
        db=cast(Any, db),
        registry=registry,
        external_agents=MagicMock(),
    )

    with pytest.raises(ValueError, match="already exists"):
        await service.create_agent(agent)

    registry.create.assert_not_awaited()
    db.commit.assert_not_awaited()


async def test_mutation_operations_commit_the_operation_session() -> None:
    agent = _agent()
    registry = MagicMock()
    registry.update = AsyncMock(return_value=agent)
    registry.delete = AsyncMock(return_value=True)
    registry.set_enabled = AsyncMock(return_value=agent)
    db = SimpleNamespace(commit=AsyncMock())
    service = AgentDefinitionManagementServiceV2(
        db=cast(Any, db),
        registry=registry,
        external_agents=MagicMock(),
    )

    assert await service.update_agent(agent) is agent
    assert await service.delete_agent("agent-1") is True
    assert await service.set_enabled("agent-1", True) is agent

    registry.update.assert_awaited_once_with(agent)
    registry.delete.assert_awaited_once_with("agent-1")
    registry.set_enabled.assert_awaited_once_with("agent-1", True)
    assert db.commit.await_count == 3


def test_definition_management_modules_are_ordered_provider_then_consumer() -> None:
    document = load_profile_document_v2(_PROFILE_PATH)
    enabled_modules = tuple(entry.module_ref for entry in document.entries if entry.enabled)

    assert AGENT_DEFINITION_REPOSITORY_PROVIDER_MODULE_V2 in enabled_modules
    assert AGENT_DEFINITION_MANAGEMENT_MODULE_V2 in enabled_modules
    assert enabled_modules.index(AGENT_DEFINITION_REPOSITORY_PROVIDER_MODULE_V2) < (
        enabled_modules.index(AGENT_DEFINITION_MANAGEMENT_MODULE_V2)
    )
    entry = next(
        entry
        for entry in document.entries
        if entry.module_ref == AGENT_DEFINITION_MANAGEMENT_MODULE_V2
    )
    assert entry.inject == {
        AGENT_DEFINITION_MANAGEMENT_REPOSITORIES_INJECT_V2: (
            "service:persistence.agent-definition-repository-provider"
        )
    }


async def test_definition_management_rejects_missing_repository_inject() -> None:
    document = load_profile_document_v2(_PROFILE_PATH)
    invalid = replace(
        document,
        entries=tuple(
            replace(entry, inject={})
            if entry.module_ref == AGENT_DEFINITION_MANAGEMENT_MODULE_V2
            else entry
            for entry in document.entries
        ),
    )
    manifest = parse_plugin_manifest_v2(json.loads(_MANIFEST_PATH.read_text(encoding="utf-8")))
    snapshot = compose_profile_v2(invalid, {manifest.plugin_id: manifest}, generation=1007)

    with pytest.raises(RuntimeV2Error) as error:
        await LoaderV2(builtin_runtime_definitions_v2()).stage(snapshot)

    assert error.value.code == "missing_required_inject"
    assert "builtin-agent-definition-management" in str(error.value)


def test_create_route_has_no_static_definition_container() -> None:
    source = inspect.getsource(create_definition)

    assert "get_container_with_db" not in source
    assert "agent_orchestrator" not in source
    assert "ACPExternalAgentConfigRepository" not in source


def test_list_route_has_no_static_definition_container() -> None:
    source = inspect.getsource(list_definitions)

    assert "get_container_with_db" not in source
    assert "agent_registry" not in source
    assert "_accessible_definition_project_ids" not in source


@pytest.mark.parametrize(
    "route",
    [get_definition, update_definition, delete_definition, set_definition_enabled],
)
def test_remaining_definition_routes_have_no_static_definition_container(route: Any) -> None:
    source = inspect.getsource(route)

    assert "get_container_with_db" not in source
    assert "agent_registry" not in source
    assert "_ensure_project_definition_access" not in source
    assert "_ensure_existing_definition_access" not in source
    assert "_validate_execution_backend(" not in source
    assert "db.commit" not in source
