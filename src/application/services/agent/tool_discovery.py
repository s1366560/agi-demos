"""Projection of one pinned V2 turn ToolSet for external discovery."""

from typing import TYPE_CHECKING, Any

from src.domain.ports.services.agent_service_port import ModelVisibleToolSetView

if TYPE_CHECKING:
    from src.application.services.skill_service import SkillService


class ToolDiscoveryService:
    """Expose only definitions from an explicitly supplied pinned ToolSet."""

    def __init__(
        self,
        redis_client: Any = None,
        skill_service: "SkillService | None" = None,
    ) -> None:
        super().__init__()
        # Retain constructor compatibility while the owning AgentService is
        # retired in a later production-composition batch. Neither dependency
        # is an authority for model-visible inventory.
        _ = (redis_client, skill_service)

    async def get_available_tools(
        self,
        project_id: str,
        tenant_id: str,
        agent_mode: str = "default",
        *,
        tool_set: ModelVisibleToolSetView,
    ) -> list[dict[str, Any]]:
        """Project the exact ToolSet used by prompt and processor consumers."""
        _ = (project_id, tenant_id, agent_mode)
        return [
            {
                "name": definition.name,
                "description": definition.description,
            }
            for definition in tool_set.definitions
        ]
