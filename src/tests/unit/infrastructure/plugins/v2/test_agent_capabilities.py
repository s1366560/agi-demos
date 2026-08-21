"""Generation-owned Skill/SubAgent contribution coverage for the v2 spine."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from src.domain.model.agent.skill import Skill
from src.domain.model.agent.subagent import AgentTrigger, SubAgent
from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.agent.core.react_agent_stream_mixin import (
    _resolve_agent_capabilities_from_runtime_v2,
)
from src.infrastructure.plugins.v2.agent_capabilities import (
    AGENT_CAPABILITY_RESOLVER_SERVICE_V2,
    SKILL_CONTRIBUTION_MODULE_V2,
    SUBAGENT_CONTRIBUTION_MODULE_V2,
    AgentCapabilityCatalogV2,
    AgentCapabilityResolverV2,
)
from src.infrastructure.plugins.v2.boundary import pin_operation_context_v2
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.composer import compose_profile_v2, load_profile_document_v2
from src.infrastructure.plugins.v2.protocol import parse_plugin_manifest_v2
from src.infrastructure.plugins.v2.runtime import GenerationManagerV2, LoaderV2, RuntimeV2Error
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2

_ROOT = Path(__file__).resolve().parents[6]
_PROFILE_PATH = _ROOT / "config/plugin-profiles/memstack-default.v2.yaml"
_MANIFEST_PATH = _ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json"


def _skill(name: str = "skill-a") -> Skill:
    return Skill(
        id=f"id-{name}",
        tenant_id="tenant-a",
        project_id="project-a",
        name=name,
        description=f"Description for {name}",
        tools=["read"],
    )


def _subagent(name: str = "subagent-a") -> SubAgent:
    return SubAgent(
        id=f"id-{name}",
        tenant_id="tenant-a",
        project_id="project-a",
        name=name,
        display_name=name.title(),
        system_prompt=f"Handle work for {name}",
        trigger=AgentTrigger(description=f"Use {name}"),
    )


@pytest.mark.unit
async def test_agent_capability_consumer_requires_pinned_operation() -> None:
    agent = SimpleNamespace(skills=[_skill()], subagents=[_subagent()])

    with pytest.raises(RuntimeV2Error) as error:
        await _resolve_agent_capabilities_from_runtime_v2(
            agent,
            tenant_id="tenant-a",
            project_id="project-a",
        )

    assert error.value.code == "operation_context_not_pinned"


@pytest.mark.unit
async def test_agent_capability_consumer_does_not_fallback_when_service_is_missing() -> None:
    agent = SimpleNamespace(skills=[_skill()], subagents=[_subagent()])
    operation = Mock()
    operation.require.side_effect = RuntimeV2Error(
        "missing_service",
        "agent capability resolver is unavailable",
    )

    with (
        patch(
            "src.infrastructure.plugins.v2.boundary.current_operation_context_v2",
            return_value=operation,
        ),
        pytest.raises(RuntimeV2Error) as error,
    ):
        await _resolve_agent_capabilities_from_runtime_v2(
            agent,
            tenant_id="tenant-a",
            project_id="project-a",
        )

    assert error.value.code == "missing_service"
    operation.require.assert_called_once_with(AGENT_CAPABILITY_RESOLVER_SERVICE_V2)


@pytest.mark.unit
async def test_agent_capability_contributions_dispose_exact_sources() -> None:
    catalog = AgentCapabilityCatalogV2()
    dispose_skills = catalog.register_skills(
        "skills-a",
        lambda **_kwargs: [_skill()],
    )
    dispose_subagents = catalog.register_subagents(
        "subagents-a",
        lambda **_kwargs: [_subagent()],
    )

    before = await catalog.resolve(
        agent=SimpleNamespace(),
        tenant_id="tenant-a",
        project_id="project-a",
    )
    assert [skill.name for skill in before.skills] == ["skill-a"]
    assert [subagent.name for subagent in before.subagents] == ["subagent-a"]

    await dispose_subagents()
    await dispose_skills()

    after = await catalog.resolve(
        agent=SimpleNamespace(),
        tenant_id="tenant-a",
        project_id="project-a",
    )
    assert after.skills == ()
    assert after.subagents == ()


@pytest.mark.unit
async def test_agent_capability_catalog_rejects_duplicate_names_across_sources() -> None:
    catalog = AgentCapabilityCatalogV2()
    _ = catalog.register_skills("skills-a", lambda **_kwargs: [_skill("duplicate")])
    _ = catalog.register_skills("skills-b", lambda **_kwargs: [_skill("duplicate")])

    with pytest.raises(RuntimeV2Error) as error:
        await catalog.resolve(
            agent=SimpleNamespace(),
            tenant_id="tenant-a",
            project_id="project-a",
        )

    assert error.value.code == "agent_capability_conflict"


@pytest.mark.unit
async def test_runtime_resolves_agent_state_only_through_explicit_contributions() -> None:
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=1,
        version=1,
    )
    agent = SimpleNamespace(skills=[_skill()], subagents=[_subagent()])

    async with pin_operation_context_v2(
        host,
        operation_id="agent-capability-consumer",
        scope=ScopeV2(kind=ScopeKindV2.ROOT),
    ) as operation:
        resolver = operation.require(AGENT_CAPABILITY_RESOLVER_SERVICE_V2)
        assert isinstance(resolver, AgentCapabilityResolverV2)
        result = await resolver.resolve(
            agent=agent,
            tenant_id="tenant-a",
            project_id="project-a",
        )

    assert result.skills == tuple(agent.skills)
    assert result.subagents == tuple(agent.subagents)
    await host.close()


@pytest.mark.unit
def test_skill_and_subagent_sources_are_explicit_profile_entries() -> None:
    document = load_profile_document_v2(_PROFILE_PATH)
    modules = {entry.module_ref for entry in document.entries if entry.enabled}

    assert SKILL_CONTRIBUTION_MODULE_V2 in modules
    assert SUBAGENT_CONTRIBUTION_MODULE_V2 in modules


@pytest.mark.unit
async def test_disabling_skill_contribution_removes_skills_without_native_fallback() -> None:
    document = load_profile_document_v2(_PROFILE_PATH)
    disabled = replace(
        document,
        entries=tuple(
            replace(entry, enabled=False)
            if entry.module_ref == SKILL_CONTRIBUTION_MODULE_V2
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
    agent = SimpleNamespace(skills=[_skill()], subagents=[_subagent()])

    try:
        async with pin_operation_context_v2(
            manager,
            operation_id="disabled-skill-contribution",
            scope=ScopeV2(kind=ScopeKindV2.ROOT),
        ) as operation:
            resolver = operation.require(AGENT_CAPABILITY_RESOLVER_SERVICE_V2)
            result = await resolver.resolve(
                agent=agent,
                tenant_id="tenant-a",
                project_id="project-a",
            )
    finally:
        await manager.close()

    assert result.skills == ()
    assert result.subagents == tuple(agent.subagents)


@pytest.mark.unit
async def test_agent_capability_provider_disappears_when_generation_unloads() -> None:
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=1,
        version=1,
    )
    async with await host.acquire() as generation:
        assert isinstance(
            generation.resolve(
                AGENT_CAPABILITY_RESOLVER_SERVICE_V2,
                ScopeV2(kind=ScopeKindV2.ROOT),
            ),
            AgentCapabilityResolverV2,
        )

    await host.close()

    with pytest.raises(RuntimeError, match="generation is disposed"):
        generation.resolve(
            AGENT_CAPABILITY_RESOLVER_SERVICE_V2,
            ScopeV2(kind=ScopeKindV2.ROOT),
        )
