"""Application-layer facade for agent routing via channel bindings."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from src.domain.model.agent.agent_definition import Agent
from src.domain.ports.agent.agent_registry import AgentRegistryPort
from src.domain.ports.agent.binding_repository import AgentBindingRepositoryPort
from src.infrastructure.agent.sisyphus.builtin_agent import build_builtin_sisyphus_agent

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AgentResolutionResult:
    agent: Agent | None
    binding_matched: bool
    reason: str = ""


class AgentRouterService:
    """Resolves which agent handles a request via binding-based resolution.

    Wraps domain ports to keep infrastructure adapters out of API endpoints.
    """

    def __init__(
        self,
        binding_repository: AgentBindingRepositoryPort,
        agent_registry: AgentRegistryPort,
    ) -> None:
        self._binding_repository = binding_repository
        self._agent_registry = agent_registry

    async def resolve_agent(
        self,
        tenant_id: str,
        channel_type: str | None = None,
        channel_id: str | None = None,
        account_id: str | None = None,
        peer_id: str | None = None,
    ) -> AgentResolutionResult:
        binding = await self._binding_repository.resolve_binding(
            tenant_id=tenant_id,
            channel_type=channel_type,
            channel_id=channel_id,
            account_id=account_id,
            peer_id=peer_id,
        )
        if binding is None:
            return AgentResolutionResult(
                agent=build_builtin_sisyphus_agent(tenant_id=tenant_id),
                binding_matched=False,
                reason="builtin_default:no_binding_match",
            )

        agent = await self._agent_registry.get_by_id(binding.agent_id, tenant_id=tenant_id)
        if agent is None:
            logger.warning(
                "Binding %s references non-existent agent %s",
                binding.id,
                binding.agent_id,
            )
            return AgentResolutionResult(
                agent=build_builtin_sisyphus_agent(tenant_id=tenant_id),
                binding_matched=True,
                reason=f"builtin_default:agent_not_found:{binding.agent_id}",
            )

        if not agent.is_enabled():
            logger.warning(
                "Binding %s references disabled agent %s (%s)",
                binding.id,
                agent.id,
                agent.name,
            )
            return AgentResolutionResult(
                agent=build_builtin_sisyphus_agent(tenant_id=tenant_id),
                binding_matched=True,
                reason=f"builtin_default:agent_disabled:{agent.id}",
            )

        return AgentResolutionResult(
            agent=agent,
            binding_matched=True,
        )
