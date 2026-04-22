"""Tool discovery service extracted from AgentService."""

import logging
from typing import TYPE_CHECKING, Any

from src.infrastructure.agent.tools.define import get_registered_tools

if TYPE_CHECKING:
    from src.application.services.skill_service import SkillService

logger = logging.getLogger(__name__)


def _ensure_tool_modules_imported() -> None:
    """Import tool modules to trigger @tool_define registration side effects.

    Each module-level @tool_define decorator registers a ToolInfo in the global
    _TOOL_REGISTRY when the module is first imported. We import them here so
    that get_registered_tools() returns complete data.
    """
    import src.infrastructure.agent.tools.clarification  # pyright: ignore[reportUnusedImport]
    import src.infrastructure.agent.tools.decision  # pyright: ignore[reportUnusedImport]
    import src.infrastructure.agent.tools.model_availability_tool  # pyright: ignore[reportUnusedImport]
    import src.infrastructure.agent.tools.multi_agent_action_tools  # pyright: ignore[reportUnusedImport]
    import src.infrastructure.agent.tools.session_status  # pyright: ignore[reportUnusedImport]
    import src.infrastructure.agent.tools.skill_installer  # pyright: ignore[reportUnusedImport]
    import src.infrastructure.agent.tools.web_scrape  # pyright: ignore[reportUnusedImport]
    import src.infrastructure.agent.tools.web_search  # noqa: F401  # pyright: ignore[reportUnusedImport]


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
            # Import to trigger registration
            import src.infrastructure.agent.tools.skill_loader  # noqa: F401  # pyright: ignore[reportUnusedImport]

            registry = get_registered_tools()
            skill_loader_info = registry.get("skill_loader")
            if skill_loader_info:
                tools_list.append(
                    {
                        "name": "skill_loader",
                        "description": skill_loader_info.description,
                    }
                )

        return tools_list

    def _build_base_tool_definitions(self) -> list[dict[str, Any]]:
        """Build and cache base tool definitions (static tools only)."""
        _ensure_tool_modules_imported()
        registry = get_registered_tools()
        _TOOL_NAME_MAP = {
            "ask_clarification": "ask_clarification",
            "request_decision": "request_decision",
            "web_search": "web_search",
            "web_scrape": "web_scrape",
            "skill_installer": "skill_installer",
            "session_status": "session_status",
            "list_available_models": "list_available_models",
            # Multi-agent structured action toolset (Track B · Agent First).
            # Each tool records one subjective decision as a typed event.
            "assign_task": "assign_task",
            "refuse_task": "refuse_task",
            "request_human_input": "request_human_input",
            "escalate": "escalate",
            "mark_conflict": "mark_conflict",
            "declare_progress": "declare_progress",
            "signal_goal_complete": "signal_goal_complete",
        }
        result: list[dict[str, Any]] = []
        for display_name, registry_name in _TOOL_NAME_MAP.items():
            info = registry.get(registry_name)
            if info:
                result.append({"name": display_name, "description": info.description})
            else:
                logger.warning("Tool '%s' not found in registry; skipping", registry_name)
        return result
