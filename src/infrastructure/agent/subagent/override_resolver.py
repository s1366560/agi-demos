"""Three-tier SubAgent override resolution: project > tenant > global."""

from __future__ import annotations

import logging

from src.domain.model.agent.subagent import SubAgent

logger = logging.getLogger(__name__)


class AgentOverrideResolver:
    """Merges SubAgent dictionaries with project > tenant > global priority.

    When the same agent name exists in multiple tiers, the highest-priority
    tier wins.  Priority order (highest first): project, tenant, global.
    """

    def resolve(
        self,
        project_agents: dict[str, SubAgent],
        tenant_agents: dict[str, SubAgent],
        global_agents: dict[str, SubAgent],
    ) -> dict[str, SubAgent]:
        """Merge three tiers of SubAgent definitions.

        Args:
            project_agents: Project-scoped agents (highest priority).
            tenant_agents: Tenant-scoped agents (medium priority).
            global_agents: Global agents (lowest priority).

        Returns:
            Merged dictionary keyed by agent name.
        """
        merged: dict[str, SubAgent] = dict(global_agents)
        merged.update(tenant_agents)
        merged.update(project_agents)

        # Log override information
        self._log_overrides(project_agents, tenant_agents, global_agents)

        return merged

    @staticmethod
    def _log_overrides(
        project_agents: dict[str, SubAgent],
        tenant_agents: dict[str, SubAgent],
        global_agents: dict[str, SubAgent],
    ) -> None:
        """Log which tier won for agents present in multiple tiers."""
        all_names = set(global_agents) | set(tenant_agents) | set(project_agents)

        for name in sorted(all_names):
            tiers: list[str] = []
            if name in global_agents:
                tiers.append("global")
            if name in tenant_agents:
                tiers.append("tenant")
            if name in project_agents:
                tiers.append("project")

            if len(tiers) > 1:
                winner = tiers[-1]  # last in priority order
                logger.info(
                    "Agent '%s' defined in [%s] - using %s override",
                    name,
                    ", ".join(tiers),
                    winner,
                )
