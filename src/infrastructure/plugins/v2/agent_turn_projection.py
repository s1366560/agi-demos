"""Thin projection from a pinned operation to the native Agent turn service."""

from __future__ import annotations

from .agent_turn_services import (
    AGENT_TURN_SERVICE_V2,
    AgentTurnResolverProtocolV2,
    AgentTurnStreamProtocolV2,
)
from .boundary import current_operation_context_v2
from .runtime import RuntimeV2Error


async def current_agent_turn_service_v2() -> AgentTurnStreamProtocolV2:
    """Resolve the native stream service from the exact pinned operation."""
    operation = current_operation_context_v2()
    resolver = operation.require(AGENT_TURN_SERVICE_V2)
    if not isinstance(resolver, AgentTurnResolverProtocolV2):
        raise RuntimeV2Error(
            "invalid_agent_turn_resolver",
            "service:agent.turn-service has an invalid resolver",
        )
    service = await resolver.resolve(operation)
    if not isinstance(service, AgentTurnStreamProtocolV2):
        raise RuntimeV2Error(
            "invalid_agent_turn_service",
            "Agent turn resolver returned an invalid stream service",
        )
    return service


__all__ = ["current_agent_turn_service_v2"]
