"""Generation-scoped builtin agent-loop Provider for the v2 runtime spine."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .runtime import ContextV2, PluginDefinitionV2, generated_contract_digest_v2

AGENT_LOOP_MODULE_V2 = "builtin://memstack/agent/loop"
AGENT_LOOP_RESOLVER_SERVICE_V2 = "service:agent-loop-resolver"


@dataclass(frozen=True, kw_only=True)
class AgentLoopSelectionV2:
    loop_id: str
    plugin_id: str
    scope: str
    implementation: object


class _BuiltinReActLoopV2:
    async def run(self, _context: object) -> None:
        raise NotImplementedError("builtin ReAct executes through the native processor path")


@dataclass(frozen=True, kw_only=True)
class BuiltinAgentLoopResolverV2:
    """Resolve the explicit repository builtin loop without subjective auto routing."""

    loop_id: str
    plugin_id: str
    implementation: object

    def resolve(self, provider_id: str, model_id: str) -> AgentLoopSelectionV2:
        if not provider_id.strip() or not model_id.strip():
            raise ValueError("provider_id and model_id must be non-empty")
        return AgentLoopSelectionV2(
            loop_id=self.loop_id,
            plugin_id=self.plugin_id,
            scope="builtin",
            implementation=self.implementation,
        )


def _apply_builtin_agent_loop_v2(
    context: ContextV2,
    config: Mapping[str, Any],
) -> None:
    loop_id = config.get("loop_id")
    if loop_id != "builtin-react":
        raise ValueError("builtin agent loop requires loop_id builtin-react")
    context.provide(
        AGENT_LOOP_RESOLVER_SERVICE_V2,
        BuiltinAgentLoopResolverV2(
            loop_id=loop_id,
            plugin_id="memstack-kernel",
            implementation=_BuiltinReActLoopV2(),
        ),
        label="builtin-agent-loop-resolver",
    )


def builtin_agent_loop_definition_v2() -> PluginDefinitionV2:
    return PluginDefinitionV2(
        module_ref=AGENT_LOOP_MODULE_V2,
        contract_digest=generated_contract_digest_v2(AGENT_LOOP_MODULE_V2),
        apply=_apply_builtin_agent_loop_v2,
    )


__all__ = [
    "AGENT_LOOP_MODULE_V2",
    "AGENT_LOOP_RESOLVER_SERVICE_V2",
    "AgentLoopSelectionV2",
    "BuiltinAgentLoopResolverV2",
    "builtin_agent_loop_definition_v2",
]
