"""Exit Plan Mode use case.

This use case handles switching a conversation out of Plan Mode,
optionally approving the plan for implementation.
"""

import logging
from typing import Optional

from src.domain.model.agent.plan import (
    NotInPlanModeError,
    Plan,
    PlanDocumentStatus,
    PlanNotFoundError,
)
from src.domain.ports.repositories import PlanRepository
from src.domain.ports.repositories.agent_repository import ConversationRepository

logger = logging.getLogger(__name__)


class ExitPlanModeUseCase:
    """Use case for exiting Plan Mode."""

    def __init__(
        self,
        plan_repository: PlanRepository,
        conversation_repository: ConversationRepository,
    ):
        """
        Initialize the use case.

        Args:
            plan_repository: Repository for Plan entities
            conversation_repository: Repository for Conversation entities
        """
        self._plan_repository = plan_repository
        self._conversation_repository = conversation_repository

    async def execute(
        self,
        conversation_id: str,
        plan_id: str,
        approve: bool = True,
        summary: Optional[str] = None,
    ) -> Plan:
        """
        Execute the use case.

        Args:
            conversation_id: The conversation to exit Plan Mode for
            plan_id: The plan document ID
            approve: Whether to approve the plan (default True)
            summary: Optional summary of the plan

        Returns:
            The updated Plan entity

        Raises:
            NotInPlanModeError: If not currently in Plan Mode
            PlanNotFoundError: If the plan doesn't exist
            ValueError: If conversation not found
        """
        # Validate conversation exists
        conversation = await self._conversation_repository.find_by_id(conversation_id)
        if not conversation:
            raise ValueError(f"Conversation not found: {conversation_id}")

        # Check if in Plan Mode
        if not conversation.is_in_plan_mode:
            raise NotInPlanModeError(conversation_id)

        # Fetch the plan
        plan = await self._plan_repository.find_by_id(plan_id)
        if not plan:
            raise PlanNotFoundError(plan_id)

        # Add summary to metadata if provided
        if summary:
            plan.add_metadata("exit_summary", summary)

        # Update plan status
        if approve:
            plan.approve()
        elif plan.status == PlanDocumentStatus.DRAFT:
            plan.mark_reviewing()

        # Persist plan changes
        await self._plan_repository.save(plan)

        # Exit Plan Mode on conversation
        conversation.exit_plan_mode()
        await self._conversation_repository.save(conversation)

        logger.info(
            f"Exited Plan Mode for conversation {conversation_id}, "
            f"plan {plan_id}, approved={approve}"
        )

        return plan
