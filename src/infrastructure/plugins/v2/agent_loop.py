"""Generation-scoped builtin agent-loop Provider for the v2 runtime spine."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from .agent_lifecycle_notifier import AgentLifecycleNotifierProtocolV2
from .runtime import ContextV2, PluginDefinitionV2, RuntimeV2Error, generated_contract_digest_v2

AGENT_LOOP_MODULE_V2 = "builtin://memstack/agent/loop"
AGENT_LOOP_RESOLVER_SERVICE_V2 = "service:agent-loop-resolver"
AGENT_LOOP_LIFECYCLE_NOTIFIER_INJECT_V2 = "lifecycle_notifier"


@dataclass(frozen=True, kw_only=True)
class AgentLoopSelectionV2:
    loop_id: str
    plugin_id: str
    scope: str
    implementation: object


@runtime_checkable
class AgentLoopResolverProtocolV2(Protocol):
    """Stable service contract exposed to Agent-loop Consumers."""

    lifecycle_notifier: AgentLifecycleNotifierProtocolV2

    def resolve(self, provider_id: str, model_id: str) -> AgentLoopSelectionV2: ...


class _BuiltinReActLoopV2:
    async def run(self, _context: object) -> None:
        raise NotImplementedError("builtin ReAct executes through the native processor path")


def validate_loop_implementation(implementation: object) -> None:
    """Fail closed when a selected v2 loop does not implement the driver contract."""
    if not callable(getattr(implementation, "run", None)):
        raise RuntimeV2Error(
            "agent_loop_implementation_invalid",
            f"agent loop implementation {type(implementation).__name__} has no callable run",
        )


@dataclass(frozen=True, kw_only=True)
class BuiltinAgentLoopResolverV2:
    """Resolve the explicit repository builtin loop without subjective auto routing."""

    loop_id: str
    plugin_id: str
    implementation: object
    lifecycle_notifier: AgentLifecycleNotifierProtocolV2

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
    lifecycle_notifier = context.require(AGENT_LOOP_LIFECYCLE_NOTIFIER_INJECT_V2)
    if not isinstance(lifecycle_notifier, AgentLifecycleNotifierProtocolV2):
        raise RuntimeV2Error(
            "agent_lifecycle_notifier_invalid",
            "agent loop lifecycle_notifier does not implement the V2 notification contract",
        )
    _ = context.provide(
        AGENT_LOOP_RESOLVER_SERVICE_V2,
        BuiltinAgentLoopResolverV2(
            loop_id=loop_id,
            plugin_id="memstack-kernel",
            implementation=_BuiltinReActLoopV2(),
            lifecycle_notifier=lifecycle_notifier,
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
    "AGENT_LOOP_LIFECYCLE_NOTIFIER_INJECT_V2",
    "AGENT_LOOP_MODULE_V2",
    "AGENT_LOOP_RESOLVER_SERVICE_V2",
    "AgentLoopResolverProtocolV2",
    "AgentLoopSelectionV2",
    "BuiltinAgentLoopResolverV2",
    "builtin_agent_loop_definition_v2",
    "validate_loop_implementation",
]
