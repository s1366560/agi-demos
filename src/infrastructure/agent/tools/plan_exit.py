"""
Plan Exit Tool for exiting Plan Mode.

This tool allows the agent to exit Plan Mode and optionally approve the plan.
Similar to OpenCode's ExitSpecMode functionality.
"""

import json
import logging
from typing import Any, Dict, Optional

from src.domain.model.agent.plan import NotInPlanModeError, PlanDocumentStatus, PlanNotFoundError
from src.domain.ports.repositories import PlanRepository
from src.infrastructure.agent.tools.base import AgentTool

logger = logging.getLogger(__name__)


class PlanExitTool(AgentTool):
    """
    Tool for exiting Plan Mode.

    When invoked, this tool:
    1. Validates the plan is ready for exit
    2. Optionally approves the plan
    3. Updates the conversation back to Build Mode
    4. Emits plan_mode_exit SSE event

    Usage:
        plan_exit = PlanExitTool(plan_repository)
        result = await plan_exit.execute(
            conversation_id="conv-123",
            plan_id="plan-456",
            approve=True,
            summary="Implement OAuth2 with JWT tokens"
        )
    """

    def __init__(
        self,
        plan_repository: PlanRepository,
        conversation_repository: Optional[Any] = None,
    ):
        """
        Initialize the plan exit tool.

        Args:
            plan_repository: Repository for Plan entities
            conversation_repository: Optional conversation repository for updating mode
        """
        super().__init__(
            name="plan_exit",
            description=(
                "Exit Plan Mode and return to Build Mode. "
                "Use this when the plan is complete and ready for implementation. "
                "Set approve=True to mark the plan as approved for implementation."
            ),
        )
        self.plan_repository = plan_repository
        self.conversation_repository = conversation_repository

    def validate_args(self, **kwargs: Any) -> bool:
        """Validate plan exit arguments."""
        if "conversation_id" not in kwargs:
            logger.error("Missing required argument: conversation_id")
            return False

        if "plan_id" not in kwargs:
            logger.error("Missing required argument: plan_id")
            return False

        return True

    async def execute(
        self,
        conversation_id: str,
        plan_id: str,
        approve: bool = True,
        summary: Optional[str] = None,
        **kwargs: Any,
    ) -> str:
        """
        Execute plan mode exit.

        Args:
            conversation_id: The conversation ID to exit Plan Mode for
            plan_id: The plan document ID
            approve: Whether to approve the plan (default True)
            summary: Optional 1-2 sentence summary of the plan

        Returns:
            JSON string with exit result

        Raises:
            NotInPlanModeError: If not currently in Plan Mode
            PlanNotFoundError: If the plan doesn't exist
        """
        # Validate arguments
        if not self.validate_args(
            conversation_id=conversation_id,
            plan_id=plan_id,
        ):
            return json.dumps(
                {
                    "success": False,
                    "error": "Invalid arguments for plan_exit",
                }
            )

        try:
            # Fetch the plan
            plan = await self.plan_repository.find_by_id(plan_id)
            if not plan:
                raise PlanNotFoundError(plan_id)

            # Check if conversation is in Plan Mode
            if self.conversation_repository:
                conversation = await self.conversation_repository.find_by_id(conversation_id)
                if conversation and not conversation.is_in_plan_mode:
                    raise NotInPlanModeError(conversation_id)

            old_status = plan.status.value

            # Add summary to metadata if provided
            if summary:
                plan.add_metadata("exit_summary", summary)

            # Approve the plan if requested
            if approve:
                plan.approve()
                await self.plan_repository.update_status(plan_id, PlanDocumentStatus.APPROVED)
            else:
                # Just mark as reviewing if not approved
                if plan.status == PlanDocumentStatus.DRAFT:
                    plan.mark_reviewing()
                    await self.plan_repository.update_status(plan_id, PlanDocumentStatus.REVIEWING)

            # Save plan changes
            await self.plan_repository.save(plan)

            # Update conversation mode back to Build
            if self.conversation_repository:
                conversation = await self.conversation_repository.find_by_id(conversation_id)
                if conversation:
                    conversation.exit_plan_mode()
                    await self.conversation_repository.save(conversation)

            logger.info(
                f"Exited Plan Mode for conversation {conversation_id}, "
                f"plan {plan_id}, approved={approve}"
            )

            return json.dumps(
                {
                    "success": True,
                    "plan_id": plan_id,
                    "approved": approve,
                    "old_status": old_status,
                    "new_status": plan.status.value,
                    "message": (
                        f"Exited Plan Mode. Plan '{plan.title}' is now {plan.status.value}. "
                        f"You can now proceed with implementation in Build Mode."
                        if approve
                        else f"Exited Plan Mode. Plan '{plan.title}' is in {plan.status.value} status."
                    ),
                }
            )

        except NotInPlanModeError as e:
            logger.warning(f"Not in Plan Mode: {e}")
            return json.dumps(
                {
                    "success": False,
                    "error": str(e),
                    "error_code": "NOT_IN_PLAN_MODE",
                }
            )
        except PlanNotFoundError as e:
            logger.warning(f"Plan not found: {e}")
            return json.dumps(
                {
                    "success": False,
                    "error": str(e),
                    "error_code": "PLAN_NOT_FOUND",
                }
            )
        except Exception as e:
            logger.error(f"Failed to exit Plan Mode: {e}")
            return json.dumps(
                {
                    "success": False,
                    "error": f"Failed to exit Plan Mode: {str(e)}",
                }
            )

    def get_parameters_schema(self) -> Dict[str, Any]:
        """Get the parameters schema for LLM function calling."""
        return {
            "type": "object",
            "properties": {
                "conversation_id": {
                    "type": "string",
                    "description": "The conversation ID to exit Plan Mode for",
                },
                "plan_id": {
                    "type": "string",
                    "description": "The plan document ID to finalize",
                },
                "approve": {
                    "type": "boolean",
                    "description": "Whether to approve the plan for implementation (default: true)",
                    "default": True,
                },
                "summary": {
                    "type": "string",
                    "description": "A 1-2 sentence high-level summary of what the plan will accomplish",
                },
            },
            "required": ["conversation_id", "plan_id"],
        }

    def get_output_schema(self) -> Dict[str, Any]:
        """Get output schema for tool composition."""
        return {
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "plan_id": {"type": "string"},
                "approved": {"type": "boolean"},
                "old_status": {"type": "string"},
                "new_status": {"type": "string"},
                "message": {"type": "string"},
                "error": {"type": "string"},
                "error_code": {"type": "string"},
            },
            "description": "Result of exiting Plan Mode",
        }
