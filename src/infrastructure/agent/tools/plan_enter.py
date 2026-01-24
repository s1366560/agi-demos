"""
Plan Enter Tool for switching to Plan Mode.

This tool allows the agent to enter Plan Mode, which provides:
- Read-only access to the codebase (explore tools only)
- Plan document editing capability
- Explicit planning before implementation

Similar to OpenCode's EnterSpecMode functionality.
"""

import json
import logging
from typing import Any, Dict, Optional

from src.domain.model.agent.plan import AlreadyInPlanModeError, Plan
from src.domain.ports.repositories import PlanRepository
from src.infrastructure.agent.tools.base import AgentTool

logger = logging.getLogger(__name__)


class PlanEnterTool(AgentTool):
    """
    Tool for entering Plan Mode.

    When invoked, this tool:
    1. Creates a new Plan document with default template
    2. Updates the conversation to Plan Mode
    3. Emits plan_mode_enter SSE event

    Usage:
        plan_enter = PlanEnterTool(plan_repository)
        result = await plan_enter.execute(
            conversation_id="conv-123",
            title="Implement user authentication",
            description="Plan for adding OAuth2 authentication"
        )
    """

    def __init__(
        self,
        plan_repository: PlanRepository,
        conversation_repository: Optional[Any] = None,
    ):
        """
        Initialize the plan enter tool.

        Args:
            plan_repository: Repository for persisting Plan entities
            conversation_repository: Optional conversation repository for updating mode
        """
        super().__init__(
            name="plan_enter",
            description=(
                "Enter Plan Mode to explore the codebase and design an implementation plan. "
                "Use this before implementing non-trivial features to get user approval. "
                "In Plan Mode, you have read-only access plus plan editing capability."
            ),
        )
        self.plan_repository = plan_repository
        self.conversation_repository = conversation_repository

    def validate_args(self, **kwargs: Any) -> bool:
        """Validate plan enter arguments."""
        if "conversation_id" not in kwargs:
            logger.error("Missing required argument: conversation_id")
            return False

        if "title" not in kwargs:
            logger.error("Missing required argument: title")
            return False

        title = kwargs["title"]
        if not isinstance(title, str) or len(title) < 3:
            logger.error("title must be a string with at least 3 characters")
            return False

        if len(title) > 200:
            logger.error("title must not exceed 200 characters")
            return False

        return True

    async def execute(
        self,
        conversation_id: str,
        title: str,
        description: Optional[str] = None,
        **kwargs: Any,
    ) -> str:
        """
        Execute plan mode entry.

        Args:
            conversation_id: The conversation ID to enter Plan Mode for
            title: Title for the new plan document
            description: Optional description to include in the plan

        Returns:
            JSON string with plan details

        Raises:
            AlreadyInPlanModeError: If already in Plan Mode
        """
        # Validate arguments
        if not self.validate_args(
            conversation_id=conversation_id,
            title=title,
        ):
            return json.dumps(
                {
                    "success": False,
                    "error": "Invalid arguments for plan_enter",
                }
            )

        try:
            # Check if already in Plan Mode (via conversation repository if available)
            if self.conversation_repository:
                conversation = await self.conversation_repository.find_by_id(conversation_id)
                if conversation and conversation.is_in_plan_mode:
                    raise AlreadyInPlanModeError(conversation_id)

            # Create new Plan document
            plan = Plan.create_default(
                conversation_id=conversation_id,
                title=title,
            )

            # Add description to content if provided
            if description:
                plan.update_content(plan.content.replace("[总结用户需求和目标...]", description))

            # Persist the plan
            await self.plan_repository.save(plan)

            # Update conversation mode if repository is available
            if self.conversation_repository:
                conversation = await self.conversation_repository.find_by_id(conversation_id)
                if conversation:
                    conversation.enter_plan_mode(plan.id)
                    await self.conversation_repository.save(conversation)

            logger.info(f"Entered Plan Mode for conversation {conversation_id}, plan {plan.id}")

            return json.dumps(
                {
                    "success": True,
                    "plan_id": plan.id,
                    "title": plan.title,
                    "status": plan.status.value,
                    "message": f"Entered Plan Mode. Created plan '{title}'. You now have read-only access to the codebase plus plan editing capability. Use plan_update to update the plan content, and plan_exit when ready to implement.",
                }
            )

        except AlreadyInPlanModeError as e:
            logger.warning(f"Already in Plan Mode: {e}")
            return json.dumps(
                {
                    "success": False,
                    "error": str(e),
                    "error_code": "ALREADY_IN_PLAN_MODE",
                }
            )
        except Exception as e:
            logger.error(f"Failed to enter Plan Mode: {e}")
            return json.dumps(
                {
                    "success": False,
                    "error": f"Failed to enter Plan Mode: {str(e)}",
                }
            )

    def get_parameters_schema(self) -> Dict[str, Any]:
        """Get the parameters schema for LLM function calling."""
        return {
            "type": "object",
            "properties": {
                "conversation_id": {
                    "type": "string",
                    "description": "The conversation ID to enter Plan Mode for",
                },
                "title": {
                    "type": "string",
                    "description": "Title for the plan document (3-200 characters, kebab-case preferred)",
                    "minLength": 3,
                    "maxLength": 200,
                },
                "description": {
                    "type": "string",
                    "description": "Optional description summarizing the task requirements",
                },
            },
            "required": ["conversation_id", "title"],
        }

    def get_output_schema(self) -> Dict[str, Any]:
        """Get output schema for tool composition."""
        return {
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "plan_id": {"type": "string"},
                "title": {"type": "string"},
                "status": {"type": "string"},
                "message": {"type": "string"},
                "error": {"type": "string"},
                "error_code": {"type": "string"},
            },
            "description": "Result of entering Plan Mode",
        }
