"""Tool discovery service extracted from AgentService."""

import logging
from typing import TYPE_CHECKING, Any

from src.infrastructure.agent.tools import (
    SkillInstallerTool,
    SkillLoaderTool,
    WebScrapeTool,
    WebSearchTool,
)

if TYPE_CHECKING:
    from src.application.services.skill_service import SkillService

logger = logging.getLogger(__name__)


class ToolDiscoveryService:
    """Handles tool listing and discovery."""

    def __init__(
        self,
        redis_client: Any = None,
        skill_service: "SkillService | None" = None,
    ) -> None:
        self._redis_client = redis_client
        self._skill_service = skill_service
        self._tool_definitions_cache: list[dict[str, Any]] | None = None

    async def get_available_tools(
        self, project_id: str, tenant_id: str, agent_mode: str = "default"
    ) -> list[dict[str, Any]]:
        """Get list of available tools for the agent."""
        if self._tool_definitions_cache is None:
            self._tool_definitions_cache = self._build_base_tool_definitions()

        tools_list = list(self._tool_definitions_cache)

        if self._skill_service:
            skill_loader = SkillLoaderTool(
                skill_service=self._skill_service,
                tenant_id=tenant_id,
                project_id=project_id,
                agent_mode=agent_mode,
            )
            await skill_loader.initialize()
            tools_list.append(
                {
                    "name": "skill_loader",
                    "description": skill_loader.description,
                }
            )

        return tools_list

    def _build_base_tool_definitions(self) -> list[dict[str, Any]]:
        """Build and cache base tool definitions (static tools only)."""
        from src.infrastructure.agent.tools import ClarificationTool, DecisionTool

        return [
            {
                "name": "ask_clarification",
                "description": ClarificationTool().description,
            },
            {
                "name": "request_decision",
                "description": DecisionTool().description,
            },
            {
                "name": "web_search",
                "description": WebSearchTool(self._redis_client).description,
            },
            {
                "name": "web_scrape",
                "description": WebScrapeTool().description,
            },
            {
                "name": "skill_installer",
                "description": SkillInstallerTool().description,
            },
        ]
