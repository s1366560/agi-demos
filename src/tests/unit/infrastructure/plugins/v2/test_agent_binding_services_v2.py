"""Generation-owned AgentBinding application seam coverage."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, Mock

import pytest

from src.domain.model.agent.agent_binding import AgentBinding
from src.domain.model.agent.agent_definition import Agent
from src.domain.model.agent.subagent import AgentTrigger
from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.plugins.v2.agent_binding_services import (
    AGENT_BINDING_MODULE_V2,
    AgentBindingAgentUnavailableV2,
    AgentBindingNotFoundV2,
    AgentBindingResolverV2,
    AgentBindingScopeMismatchV2,
    AgentBindingServiceV2,
)
from src.infrastructure.plugins.v2.boundary import OPERATION_DB_SESSION_SERVICE_V2
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.composer import compose_profile_v2, load_profile_document_v2
from src.infrastructure.plugins.v2.protocol import parse_plugin_manifest_v2
from src.infrastructure.plugins.v2.runtime import LoaderV2, RuntimeV2Error

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[6]
_PROFILE_PATH = _ROOT / "config/plugin-profiles/memstack-default.v2.yaml"
_MANIFEST_PATH = _ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json"
_SERVICE_PATH = _ROOT / "src/infrastructure/plugins/v2/agent_binding_services.py"


def _agent(
    *,
    tenant_id: str = "tenant-a",
    project_id: str | None = None,
) -> Agent:
    return Agent(
        id="agent-a",
        tenant_id=tenant_id,
        project_id=project_id,
        name="agent-a",
        display_name="Agent A",
        system_prompt="Manage tenant bindings.",
        trigger=AgentTrigger(description="Use for binding tests"),
    )


def _operation(*, tenant_id: str = "tenant-a", project_id: str | None = None) -> Any:
    return SimpleNamespace(
        context=SimpleNamespace(
            scope=ScopeV2(
                kind=(ScopeKindV2.PROJECT if project_id is not None else ScopeKindV2.TENANT),
                tenant_id=tenant_id,
                project_id=project_id,
            )
        )
    )


def _service(
    *,
    agent: object | None = None,
) -> tuple[AgentBindingServiceV2, SimpleNamespace, SimpleNamespace]:
    binding_repository = SimpleNamespace(
        create=AsyncMock(side_effect=lambda binding: binding),
        list_by_agent=AsyncMock(return_value=[]),
        list_by_tenant=AsyncMock(return_value=[]),
        get_by_id=AsyncMock(return_value=None),
        delete=AsyncMock(return_value=True),
        set_enabled=AsyncMock(),
        find_by_group=AsyncMock(return_value=[]),
        resolve_binding_with_trace=AsyncMock(return_value=(None, [])),
    )
    agent_definitions = SimpleNamespace(resolve=AsyncMock(return_value=agent))
    service = AgentBindingServiceV2(
        operation=cast(Any, _operation()),
        binding_repository=cast(Any, binding_repository),
        agent_definitions=cast(Any, agent_definitions),
    )
    return service, binding_repository, agent_definitions


async def test_binding_service_creates_only_for_tenant_level_agent() -> None:
    agent = _agent()
    service, repository, agent_definitions = _service(agent=agent)
    binding = AgentBinding(
        id="binding-a",
        tenant_id="tenant-a",
        agent_id="agent-a",
        channel_type="slack",
    )

    created = await service.create(binding)

    assert created is binding
    agent_definitions.resolve.assert_awaited_once_with(
        agent_id="agent-a",
        tenant_id="tenant-a",
        project_id=None,
    )
    repository.create.assert_awaited_once_with(binding)


@pytest.mark.parametrize(
    "agent",
    [
        None,
        _agent(tenant_id="tenant-b"),
        _agent(project_id="project-a"),
    ],
)
async def test_binding_service_rejects_unavailable_or_wrong_scope_agent(
    agent: object | None,
) -> None:
    service, repository, _agent_definitions = _service(agent=agent)
    binding = AgentBinding(id="binding-a", tenant_id="tenant-a", agent_id="agent-a")

    with pytest.raises(AgentBindingAgentUnavailableV2):
        await service.create(binding)

    repository.create.assert_not_awaited()


async def test_binding_service_rejects_cross_tenant_create_before_definition_lookup() -> None:
    service, repository, agent_definitions = _service(agent=_agent(tenant_id="tenant-b"))
    binding = AgentBinding(id="binding-a", tenant_id="tenant-b", agent_id="agent-a")

    with pytest.raises(AgentBindingScopeMismatchV2):
        await service.create(binding)

    agent_definitions.resolve.assert_not_awaited()
    repository.create.assert_not_awaited()


async def test_binding_service_lists_only_exact_tenant_rows() -> None:
    service, repository, _agent_definitions = _service()
    local = AgentBinding(id="binding-a", tenant_id="tenant-a", agent_id="agent-a")
    foreign = AgentBinding(id="binding-b", tenant_id="tenant-b", agent_id="agent-a")
    repository.list_by_agent.return_value = [local, foreign]
    repository.list_by_tenant.return_value = [local, foreign]

    by_agent = await service.list_bindings(agent_id="agent-a", enabled_only=True)
    by_tenant = await service.list_bindings(agent_id=None, enabled_only=False)

    assert by_agent == [local]
    assert by_tenant == [local]
    repository.list_by_agent.assert_awaited_once_with(
        agent_id="agent-a",
        enabled_only=True,
    )
    repository.list_by_tenant.assert_awaited_once_with(
        tenant_id="tenant-a",
        enabled_only=False,
    )


async def test_binding_service_mutations_fail_closed_for_missing_or_foreign_rows() -> None:
    service, repository, _agent_definitions = _service()

    with pytest.raises(AgentBindingNotFoundV2):
        await service.delete("missing")
    repository.delete.assert_not_awaited()

    repository.get_by_id.return_value = AgentBinding(
        id="binding-b",
        tenant_id="tenant-b",
        agent_id="agent-b",
    )
    with pytest.raises(AgentBindingScopeMismatchV2):
        await service.set_enabled("binding-b", enabled=False)
    repository.set_enabled.assert_not_awaited()


async def test_binding_service_deletes_and_updates_exact_tenant_rows() -> None:
    service, repository, _agent_definitions = _service()
    binding = AgentBinding(id="binding-a", tenant_id="tenant-a", agent_id="agent-a")
    updated = AgentBinding(
        id="binding-a",
        tenant_id="tenant-a",
        agent_id="agent-a",
        enabled=False,
    )
    repository.get_by_id.return_value = binding
    repository.set_enabled.return_value = updated

    deleted = await service.delete("binding-a")
    result = await service.set_enabled("binding-a", enabled=False)

    assert deleted is True
    assert result is updated
    repository.delete.assert_awaited_once_with("binding-a")
    repository.set_enabled.assert_awaited_once_with("binding-a", False)


async def test_binding_service_group_and_match_results_are_tenant_scoped() -> None:
    agent = _agent()
    service, repository, agent_definitions = _service(agent=agent)
    local = AgentBinding(
        id="binding-a",
        tenant_id="tenant-a",
        agent_id="agent-a",
        group_id="group-a",
    )
    foreign = AgentBinding(
        id="binding-b",
        tenant_id="tenant-b",
        agent_id="agent-b",
        group_id="group-a",
    )
    repository.find_by_group.return_value = [local, foreign]
    repository.resolve_binding_with_trace.return_value = (
        local,
        [{"binding_id": "binding-a", "selected": True}],
    )

    grouped = await service.list_group("group-a")
    match = await service.resolve_with_trace(
        channel_type="slack",
        channel_id="channel-a",
        account_id=None,
        peer_id=None,
    )

    assert grouped == [local]
    assert match.binding is local
    assert match.agent_name == "agent-a"
    assert match.trace == ({"binding_id": "binding-a", "selected": True},)
    agent_definitions.resolve.assert_awaited_once_with(
        agent_id="agent-a",
        tenant_id="tenant-a",
        project_id=None,
    )


async def test_binding_service_rejects_cross_tenant_match() -> None:
    service, repository, agent_definitions = _service()
    repository.resolve_binding_with_trace.return_value = (
        AgentBinding(id="binding-b", tenant_id="tenant-b", agent_id="agent-b"),
        [],
    )

    with pytest.raises(AgentBindingScopeMismatchV2):
        await service.resolve_with_trace(
            channel_type="slack",
            channel_id=None,
            account_id=None,
            peer_id=None,
        )

    agent_definitions.resolve.assert_not_awaited()


def test_binding_resolver_requires_tenant_operation_and_operation_db() -> None:
    binding_factory = Mock()
    agent_definitions = SimpleNamespace(resolve=AsyncMock())
    resolver = AgentBindingResolverV2(
        binding_repository_factory=cast(Any, binding_factory),
        agent_definitions=cast(Any, agent_definitions),
    )

    with pytest.raises(RuntimeV2Error, match="tenant-scoped"):
        resolver.resolve(cast(Any, _operation(project_id="project-a")))

    db = object()
    operation = _operation()
    operation.require = lambda service: (
        db
        if service == OPERATION_DB_SESSION_SERVICE_V2
        else pytest.fail(f"unexpected service: {service}")
    )
    service = resolver.resolve(cast(Any, operation))

    assert service.operation is operation
    binding_factory.assert_called_once_with(db)
    assert service.agent_definitions is agent_definitions


def test_binding_module_is_explicit_in_the_default_profile() -> None:
    document = load_profile_document_v2(_PROFILE_PATH)
    entry = next(entry for entry in document.entries if entry.module_ref == AGENT_BINDING_MODULE_V2)

    assert entry.enabled is True
    assert entry.inject == {"agent_definitions": "service:agent-definition-resolver"}
    assert entry.config == {"strategy": "operation-scoped-provider"}


async def test_binding_module_rejects_missing_definition_inject_without_fallback() -> None:
    document = load_profile_document_v2(_PROFILE_PATH)
    binding_entry = next(
        entry for entry in document.entries if entry.module_ref == AGENT_BINDING_MODULE_V2
    )
    invalid = replace(
        document,
        entries=tuple(
            replace(entry, inject={}) if entry.entry_id == binding_entry.entry_id else entry
            for entry in document.entries
        ),
    )
    manifest = parse_plugin_manifest_v2(json.loads(_MANIFEST_PATH.read_text(encoding="utf-8")))
    snapshot = compose_profile_v2(invalid, {manifest.plugin_id: manifest}, generation=995)

    with pytest.raises(RuntimeV2Error) as error:
        await LoaderV2(builtin_runtime_definitions_v2()).stage(snapshot)

    assert error.value.code == "missing_required_inject"


def test_binding_provider_has_no_sql_agent_registry_or_builtin_fallback() -> None:
    source = _SERVICE_PATH.read_text(encoding="utf-8")

    assert "SqlAgentRegistryRepository" not in source
    assert "get_builtin_agent" not in source
