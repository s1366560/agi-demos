"""Binding-aware router -- resolves which agent handles a channel message.

Wraps the existing ChannelRouter and adds agent resolution via
AgentBindingRepositoryPort + AgentRegistryPort.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from src.domain.model.agent.agent_definition import Agent
from src.domain.ports.agent.agent_registry import AgentRegistryPort
from src.domain.ports.agent.binding_repository import AgentBindingRepositoryPort
from src.infrastructure.agent.channels.channel_message import ChannelMessage
from src.infrastructure.agent.channels.channel_router import ChannelRouter, RouteResult

logger = logging.getLogger(__name__)


@dataclass
class AgentRouteResult:
    """Outcome of routing a ChannelMessage through the binding layer.

    Attributes:
        agent: Resolved Agent to handle the message (None if no binding found).
        route_result: The underlying ChannelRouter RouteResult with conversation_id set.
    """

    agent: Agent | None
    route_result: RouteResult


class BindingRouter:
    """Routes channel messages to the correct agent using binding resolution.

    Wraps ChannelRouter for conversation mapping and adds agent resolution
    via AgentBindingRepositoryPort.resolve_binding().

    When no binding matches, agent is None -- callers fall back to default behavior.
    """

    def __init__(
        self,
        binding_repository: AgentBindingRepositoryPort,
        agent_registry: AgentRegistryPort,
        channel_router: ChannelRouter,
    ) -> None:
        self._binding_repository = binding_repository
        self._agent_registry = agent_registry
        self._channel_router = channel_router

    async def resolve_agent(
        self,
        tenant_id: str,
        channel_type: str | None = None,
        channel_id: str | None = None,
        account_id: str | None = None,
        peer_id: str | None = None,
    ) -> Agent | None:
        """Resolve which agent should handle messages for a given channel context.

        Uses specificity-based binding resolution (most-specific wins).
        Returns None if no binding matches or the bound agent is not found/disabled.

        Args:
            tenant_id: Tenant scope.
            channel_type: Channel transport type.
            channel_id: Specific channel instance.
            account_id: User account identifier.
            peer_id: Peer identity.

        Returns:
            The resolved Agent, or None if no match.
        """
        binding = await self._binding_repository.resolve_binding(
            tenant_id=tenant_id,
            channel_type=channel_type,
            channel_id=channel_id,
            account_id=account_id,
            peer_id=peer_id,
        )
        if binding is None:
            logger.debug(
                "No binding found for tenant=%s channel=%s/%s",
                tenant_id,
                channel_type,
                channel_id,
            )
            return None

        agent = await self._agent_registry.get_by_id(binding.agent_id)
        if agent is None:
            logger.warning(
                "Binding %s references non-existent agent %s",
                binding.id,
                binding.agent_id,
            )
            return None

        if not agent.is_enabled():
            logger.warning(
                "Binding %s references disabled agent %s (%s)",
                binding.id,
                agent.id,
                agent.name,
            )
            return None

        logger.info(
            "Resolved agent %s (%s) for tenant=%s channel=%s/%s",
            agent.id,
            agent.name,
            tenant_id,
            channel_type,
            channel_id,
        )
        return agent

    async def route(self, message: ChannelMessage) -> AgentRouteResult:
        """Route a channel message: resolve agent + conversation.

        Combines binding-based agent resolution with ChannelRouter's
        conversation mapping.

        Args:
            message: The incoming channel message.

        Returns:
            AgentRouteResult with resolved agent and route result.
        """
        # Resolve agent via bindings
        agent = await self.resolve_agent(
            tenant_id=message.tenant_id or "",
            channel_type=message.channel_type,
            channel_id=message.channel_id,
            account_id=message.sender_id,
        )

        # Resolve conversation via existing ChannelRouter
        route_result = self._channel_router.route(message)

        return AgentRouteResult(
            agent=agent,
            route_result=route_result,
        )
