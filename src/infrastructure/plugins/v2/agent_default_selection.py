"""Profile-owned default agent selection for the V2 runtime spine."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal, Protocol, runtime_checkable

from src.domain.model.agent.agent_definition import Agent

from .agent_definition import AgentDefinitionCatalogProtocolV2
from .runtime import ContextV2, PluginDefinitionV2, RuntimeV2Error, generated_contract_digest_v2

AGENT_DEFAULT_SELECTION_MODULE_V2 = "builtin://memstack/agent/default-selection"
AGENT_DEFAULT_SELECTION_SERVICE_V2 = "service:agent-default-selection"
AGENT_DEFAULT_SELECTION_CATALOG_INJECT_V2 = "catalog"

type AgentDefaultSelectionSourceV2 = Literal["profile-default"]


@dataclass(frozen=True, kw_only=True)
class AgentDefaultSelectionResolutionV2:
    """Default definition selected by one pinned generation."""

    agent_id: str
    source: AgentDefaultSelectionSourceV2


@runtime_checkable
class AgentDefaultSelectionResolverProtocolV2(Protocol):
    """Structural contract consumed when no explicit agent has been selected."""

    def resolve(
        self,
        *,
        tenant_id: str,
        project_id: str,
    ) -> AgentDefaultSelectionResolutionV2: ...


@dataclass(frozen=True, kw_only=True)
class AgentDefaultSelectionResolverV2:
    """Resolve the Profile default only when its definition contribution is active."""

    default_agent_id: str
    catalog: AgentDefinitionCatalogProtocolV2

    def resolve(
        self,
        *,
        tenant_id: str,
        project_id: str,
    ) -> AgentDefaultSelectionResolutionV2:
        if not tenant_id.strip() or not project_id.strip():
            raise RuntimeV2Error(
                "invalid_agent_default_scope",
                "agent default selection requires non-empty tenant and project scopes",
            )

        selected = self.catalog.resolve(
            agent_id=self.default_agent_id,
            tenant_id=tenant_id,
            project_id=project_id,
        )
        if selected is None:
            raise RuntimeV2Error(
                "agent_default_definition_not_found",
                f"agent default definition {self.default_agent_id} is unavailable",
            )
        if not isinstance(selected, Agent):
            raise RuntimeV2Error(
                "invalid_service_implementation",
                "agent default definition contribution returned an invalid agent",
            )
        if selected.tenant_id != tenant_id or selected.project_id not in {None, project_id}:
            raise RuntimeV2Error(
                "agent_default_scope_mismatch",
                "agent default definition does not match the pinned operation scope",
            )
        if not selected.is_enabled():
            raise RuntimeV2Error(
                "agent_default_definition_disabled",
                f"agent default definition {self.default_agent_id} is disabled",
            )
        return AgentDefaultSelectionResolutionV2(
            agent_id=self.default_agent_id,
            source="profile-default",
        )


def _apply_agent_default_selection_v2(
    context: ContextV2,
    config: Mapping[str, Any],
) -> None:
    default_agent_id = config.get("default_agent_id")
    if not isinstance(default_agent_id, str) or not default_agent_id.strip():
        raise ValueError("agent default selection requires a non-empty default_agent_id")
    catalog = context.require(AGENT_DEFAULT_SELECTION_CATALOG_INJECT_V2)
    if not isinstance(catalog, AgentDefinitionCatalogProtocolV2):
        raise RuntimeV2Error(
            "invalid_service_implementation",
            "agent definition catalog service has an invalid implementation",
        )
    _ = context.provide(
        AGENT_DEFAULT_SELECTION_SERVICE_V2,
        AgentDefaultSelectionResolverV2(
            default_agent_id=default_agent_id.strip(),
            catalog=catalog,
        ),
        label="agent-default-selection",
    )


def builtin_agent_default_selection_definition_v2() -> PluginDefinitionV2:
    return PluginDefinitionV2(
        module_ref=AGENT_DEFAULT_SELECTION_MODULE_V2,
        contract_digest=generated_contract_digest_v2(AGENT_DEFAULT_SELECTION_MODULE_V2),
        apply=_apply_agent_default_selection_v2,
    )


__all__ = [
    "AGENT_DEFAULT_SELECTION_CATALOG_INJECT_V2",
    "AGENT_DEFAULT_SELECTION_MODULE_V2",
    "AGENT_DEFAULT_SELECTION_SERVICE_V2",
    "AgentDefaultSelectionResolutionV2",
    "AgentDefaultSelectionResolverProtocolV2",
    "AgentDefaultSelectionResolverV2",
    "builtin_agent_default_selection_definition_v2",
]
