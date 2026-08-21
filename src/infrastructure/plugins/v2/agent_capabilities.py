"""Generation-owned Skill and SubAgent contribution catalogs for the v2 spine."""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol, TypeVar, cast, runtime_checkable

from src.domain.model.agent.skill import Skill
from src.domain.model.agent.subagent import SubAgent

from .runtime import ContextV2, PluginDefinitionV2, RuntimeV2Error, generated_contract_digest_v2

AGENT_CAPABILITY_MODULE_V2 = "builtin://memstack/agent/capability-set"
SKILL_CONTRIBUTION_MODULE_V2 = "builtin://memstack/agent/skill-contribution"
SUBAGENT_CONTRIBUTION_MODULE_V2 = "builtin://memstack/agent/subagent-contribution"
AGENT_CAPABILITY_CATALOG_SERVICE_V2 = "service:agent-capability-catalog"
AGENT_CAPABILITY_RESOLVER_SERVICE_V2 = "service:agent-capability-resolver"

type CapabilityDisposerV2 = Callable[[], None | Awaitable[None]]
type SkillContributionV2 = Callable[..., Sequence[Skill] | Awaitable[Sequence[Skill]]]
type SubAgentContributionV2 = Callable[
    ...,
    Sequence[SubAgent] | Awaitable[Sequence[SubAgent]],
]

_CapabilityT = TypeVar("_CapabilityT", Skill, SubAgent)
_ContributionT = TypeVar("_ContributionT", bound=Callable[..., object])


@dataclass(frozen=True, kw_only=True)
class AgentCapabilitySetV2:
    """Immutable capability view resolved from one pinned generation."""

    skills: tuple[Skill, ...]
    subagents: tuple[SubAgent, ...]


@runtime_checkable
class AgentCapabilityCatalogProtocolV2(Protocol):
    """Mutable contribution catalog owned by one staged generation."""

    def register_skills(
        self,
        source_id: str,
        contribution: SkillContributionV2,
    ) -> CapabilityDisposerV2: ...

    def register_subagents(
        self,
        source_id: str,
        contribution: SubAgentContributionV2,
    ) -> CapabilityDisposerV2: ...

    async def resolve(
        self,
        *,
        agent: object,
        tenant_id: str,
        project_id: str,
    ) -> AgentCapabilitySetV2: ...


class AgentCapabilityCatalogV2:
    """Ordered Skill/SubAgent sources populated only by active Profile entries."""

    def __init__(self) -> None:
        super().__init__()
        self._skill_sources: dict[str, SkillContributionV2] = {}
        self._subagent_sources: dict[str, SubAgentContributionV2] = {}

    def register_skills(
        self,
        source_id: str,
        contribution: SkillContributionV2,
    ) -> CapabilityDisposerV2:
        return self._register_source(
            sources=self._skill_sources,
            source_id=source_id,
            contribution=contribution,
            kind="skill",
        )

    def register_subagents(
        self,
        source_id: str,
        contribution: SubAgentContributionV2,
    ) -> CapabilityDisposerV2:
        return self._register_source(
            sources=self._subagent_sources,
            source_id=source_id,
            contribution=contribution,
            kind="subagent",
        )

    @staticmethod
    def _register_source(
        *,
        sources: dict[str, _ContributionT],
        source_id: str,
        contribution: _ContributionT,
        kind: str,
    ) -> CapabilityDisposerV2:
        normalized_source_id = source_id.strip()
        if not normalized_source_id:
            raise RuntimeV2Error(
                "invalid_agent_capability_contribution",
                f"{kind} contribution requires a non-empty source_id",
            )
        if normalized_source_id in sources:
            raise RuntimeV2Error(
                "agent_capability_source_conflict",
                f"{kind} source {normalized_source_id} already has a contribution",
            )
        sources[normalized_source_id] = contribution

        async def dispose() -> None:
            if sources.get(normalized_source_id) is contribution:
                _ = sources.pop(normalized_source_id, None)

        return dispose

    async def resolve(
        self,
        *,
        agent: object,
        tenant_id: str,
        project_id: str,
    ) -> AgentCapabilitySetV2:
        if not tenant_id.strip():
            raise ValueError("tenant_id must be non-empty")
        if not project_id.strip():
            raise ValueError("project_id must be non-empty")
        skills = await self._resolve_sources(
            sources=self._skill_sources,
            expected_type=Skill,
            kind="skill",
            agent=agent,
            tenant_id=tenant_id,
            project_id=project_id,
        )
        subagents = await self._resolve_sources(
            sources=self._subagent_sources,
            expected_type=SubAgent,
            kind="subagent",
            agent=agent,
            tenant_id=tenant_id,
            project_id=project_id,
        )
        return AgentCapabilitySetV2(skills=skills, subagents=subagents)

    @staticmethod
    async def _resolve_sources(
        *,
        sources: Mapping[str, Callable[..., object]],
        expected_type: type[_CapabilityT],
        kind: str,
        agent: object,
        tenant_id: str,
        project_id: str,
    ) -> tuple[_CapabilityT, ...]:
        resolved: list[_CapabilityT] = []
        owner_by_name: dict[str, str] = {}
        for source_id, contribution in sources.items():
            result = contribution(
                agent=agent,
                tenant_id=tenant_id,
                project_id=project_id,
            )
            if inspect.isawaitable(result):
                result = await result
            if not isinstance(result, Sequence) or isinstance(result, (str, bytes)):
                raise RuntimeV2Error(
                    "invalid_agent_capability_contribution",
                    f"{kind} source {source_id} returned a non-sequence",
                )
            for capability in cast("Sequence[object]", result):
                if not isinstance(capability, expected_type):
                    raise RuntimeV2Error(
                        "invalid_agent_capability_contribution",
                        f"{kind} source {source_id} returned an invalid capability",
                    )
                AgentCapabilityCatalogV2._validate_scope(
                    capability=capability,
                    kind=kind,
                    source_id=source_id,
                    tenant_id=tenant_id,
                    project_id=project_id,
                )
                normalized_name = capability.name.strip().casefold()
                previous_source = owner_by_name.get(normalized_name)
                if previous_source is not None:
                    raise RuntimeV2Error(
                        "agent_capability_conflict",
                        f"{kind} {capability.name} duplicate sources: {previous_source}, {source_id}",
                    )
                owner_by_name[normalized_name] = source_id
                resolved.append(capability)
        return tuple(resolved)

    @staticmethod
    def _validate_scope(
        *,
        capability: Skill | SubAgent,
        kind: str,
        source_id: str,
        tenant_id: str,
        project_id: str,
    ) -> None:
        if capability.tenant_id != tenant_id:
            raise RuntimeV2Error(
                "agent_capability_scope_mismatch",
                f"{kind} source {source_id} returned a capability for another tenant",
            )
        capability_project_id = capability.project_id
        if capability_project_id is not None and capability_project_id != project_id:
            raise RuntimeV2Error(
                "agent_capability_scope_mismatch",
                f"{kind} source {source_id} returned a capability for another project",
            )


@runtime_checkable
class AgentCapabilityResolverProtocolV2(Protocol):
    """Structural contract consumed by pinned Agent turns."""

    async def resolve(
        self,
        *,
        agent: object,
        tenant_id: str,
        project_id: str,
    ) -> AgentCapabilitySetV2: ...


@dataclass(frozen=True, kw_only=True)
class AgentCapabilityResolverV2:
    """Resolve the complete Skill/SubAgent set from one generation catalog."""

    strategy: str
    catalog: AgentCapabilityCatalogProtocolV2

    async def resolve(
        self,
        *,
        agent: object,
        tenant_id: str,
        project_id: str,
    ) -> AgentCapabilitySetV2:
        return await self.catalog.resolve(
            agent=agent,
            tenant_id=tenant_id,
            project_id=project_id,
        )


def _apply_agent_capability_catalog_v2(
    context: ContextV2,
    config: Mapping[str, Any],
) -> None:
    strategy = config.get("strategy")
    if strategy != "ordered-contributions":
        raise ValueError("agent capability provider requires strategy ordered-contributions")
    catalog = AgentCapabilityCatalogV2()
    _ = context.provide(
        AGENT_CAPABILITY_CATALOG_SERVICE_V2,
        catalog,
        label="agent-capability-catalog",
    )
    _ = context.provide(
        AGENT_CAPABILITY_RESOLVER_SERVICE_V2,
        AgentCapabilityResolverV2(strategy=strategy, catalog=catalog),
        label="agent-capability-resolver",
    )


def _agent_state_skills_v2(*, agent: object, **_kwargs: object) -> Sequence[Skill]:
    skills = getattr(agent, "skills", None)
    if not isinstance(skills, Sequence) or isinstance(skills, (str, bytes)):
        raise RuntimeV2Error(
            "invalid_agent_capability_contribution",
            "agent-owned skill contribution requires a sequence",
        )
    return cast("Sequence[Skill]", skills)


def _agent_state_subagents_v2(*, agent: object, **_kwargs: object) -> Sequence[SubAgent]:
    subagents = getattr(agent, "subagents", None)
    if not isinstance(subagents, Sequence) or isinstance(subagents, (str, bytes)):
        raise RuntimeV2Error(
            "invalid_agent_capability_contribution",
            "agent-owned subagent contribution requires a sequence",
        )
    return cast("Sequence[SubAgent]", subagents)


def _apply_skill_contribution_v2(
    context: ContextV2,
    config: Mapping[str, Any],
) -> CapabilityDisposerV2:
    if config.get("strategy") != "agent-runtime-state":
        raise ValueError("skill contribution requires strategy agent-runtime-state")
    source_id = config.get("source_id")
    if source_id != "agent-owned-skills":
        raise ValueError("skill contribution requires source_id agent-owned-skills")
    catalog = context.require("catalog")
    if not isinstance(catalog, AgentCapabilityCatalogProtocolV2):
        raise RuntimeV2Error(
            "invalid_service_implementation",
            "agent-capability catalog service has an invalid implementation",
        )
    return catalog.register_skills(source_id, _agent_state_skills_v2)


def _apply_subagent_contribution_v2(
    context: ContextV2,
    config: Mapping[str, Any],
) -> CapabilityDisposerV2:
    if config.get("strategy") != "agent-runtime-state":
        raise ValueError("subagent contribution requires strategy agent-runtime-state")
    source_id = config.get("source_id")
    if source_id != "agent-owned-subagents":
        raise ValueError("subagent contribution requires source_id agent-owned-subagents")
    catalog = context.require("catalog")
    if not isinstance(catalog, AgentCapabilityCatalogProtocolV2):
        raise RuntimeV2Error(
            "invalid_service_implementation",
            "agent-capability catalog service has an invalid implementation",
        )
    return catalog.register_subagents(source_id, _agent_state_subagents_v2)


def builtin_agent_capability_definition_v2() -> PluginDefinitionV2:
    return PluginDefinitionV2(
        module_ref=AGENT_CAPABILITY_MODULE_V2,
        contract_digest=generated_contract_digest_v2(AGENT_CAPABILITY_MODULE_V2),
        apply=_apply_agent_capability_catalog_v2,
    )


def builtin_skill_contribution_v2() -> PluginDefinitionV2:
    return PluginDefinitionV2(
        module_ref=SKILL_CONTRIBUTION_MODULE_V2,
        contract_digest=generated_contract_digest_v2(SKILL_CONTRIBUTION_MODULE_V2),
        apply=_apply_skill_contribution_v2,
    )


def builtin_subagent_contribution_v2() -> PluginDefinitionV2:
    return PluginDefinitionV2(
        module_ref=SUBAGENT_CONTRIBUTION_MODULE_V2,
        contract_digest=generated_contract_digest_v2(SUBAGENT_CONTRIBUTION_MODULE_V2),
        apply=_apply_subagent_contribution_v2,
    )


__all__ = [
    "AGENT_CAPABILITY_CATALOG_SERVICE_V2",
    "AGENT_CAPABILITY_MODULE_V2",
    "AGENT_CAPABILITY_RESOLVER_SERVICE_V2",
    "SKILL_CONTRIBUTION_MODULE_V2",
    "SUBAGENT_CONTRIBUTION_MODULE_V2",
    "AgentCapabilityCatalogProtocolV2",
    "AgentCapabilityCatalogV2",
    "AgentCapabilityResolverProtocolV2",
    "AgentCapabilityResolverV2",
    "AgentCapabilitySetV2",
    "builtin_agent_capability_definition_v2",
    "builtin_skill_contribution_v2",
    "builtin_subagent_contribution_v2",
]
