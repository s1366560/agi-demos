"""Generation-scoped agent-definition Provider for the v2 runtime spine."""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any

from .runtime import ContextV2, PluginDefinitionV2, generated_contract_digest_v2

AGENT_DEFINITION_MODULE_V2 = "builtin://memstack/agent/definition"
AGENT_DEFINITION_RESOLVER_SERVICE_V2 = "service:agent-definition-resolver"

type AgentDefinitionLoaderV2 = Callable[..., object | Awaitable[object | None] | None]


@dataclass(frozen=True, kw_only=True)
class AgentDefinitionResolverV2:
    """Resolve an explicit agent ID through the active native definition loader."""

    strategy: str

    async def resolve(
        self,
        *,
        loader: AgentDefinitionLoaderV2,
        agent_id: str,
        tenant_id: str,
        project_id: str,
    ) -> object | None:
        if not agent_id.strip():
            raise ValueError("agent_id must be non-empty")
        if not tenant_id.strip():
            raise ValueError("tenant_id must be non-empty")
        result = loader(
            agent_id=agent_id,
            tenant_id=tenant_id,
            project_id=project_id,
        )
        if inspect.isawaitable(result):
            result = await result
        return result


def _apply_agent_definition_resolver_v2(
    context: ContextV2,
    config: Mapping[str, Any],
) -> None:
    strategy = config.get("strategy")
    if strategy != "explicit-id":
        raise ValueError("agent-definition provider requires strategy explicit-id")
    context.provide(
        AGENT_DEFINITION_RESOLVER_SERVICE_V2,
        AgentDefinitionResolverV2(strategy=strategy),
        label="agent-definition-resolver",
    )


def builtin_agent_definition_v2() -> PluginDefinitionV2:
    return PluginDefinitionV2(
        module_ref=AGENT_DEFINITION_MODULE_V2,
        contract_digest=generated_contract_digest_v2(AGENT_DEFINITION_MODULE_V2),
        apply=_apply_agent_definition_resolver_v2,
    )


__all__ = [
    "AGENT_DEFINITION_MODULE_V2",
    "AGENT_DEFINITION_RESOLVER_SERVICE_V2",
    "AgentDefinitionResolverV2",
    "builtin_agent_definition_v2",
]
