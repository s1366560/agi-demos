"""Enter Plan Mode use case.

This use case handles switching a conversation into Plan Mode,
creating a new Plan document for the agent to work with.
"""

import logging
from typing import Optional

from src.domain.model.agent.plan import AlreadyInPlanModeError, Plan
from src.domain.ports.repositories import PlanRepository
from src.domain.ports.repositories.agent_repository import ConversationRepository

logger = logging.getLogger(__name__)


class EnterPlanModeUseCase:
    """Use case for entering Plan Mode."""

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
        title: str,
        description: Optional[str] = None,
    ) -> Plan:
        """
        Execute the use case.

        Args:
            conversation_id: The conversation to enter Plan Mode for
            title: Title for the new plan document
            description: Optional description to include in the plan

        Returns:
            The created Plan entity

        Raises:
            AlreadyInPlanModeError: If already in Plan Mode
            ValueError: If conversation not found
        """
        # Validate conversation exists
        conversation = await self._conversation_repository.find_by_id(conversation_id)
        if not conversation:
            raise ValueError(f"Conversation not found: {conversation_id}")

        # Check if already in Plan Mode
        if conversation.is_in_plan_mode:
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
        await self._plan_repository.save(plan)

        # Update conversation to Plan Mode
        conversation.enter_plan_mode(plan.id)
        await self._conversation_repository.save(conversation)

        logger.info(f"Entered Plan Mode for conversation {conversation_id}, created plan {plan.id}")

        return plan
