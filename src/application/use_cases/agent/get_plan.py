"""Get Plan use case.

This use case handles retrieving plan documents by ID or conversation.
"""

import logging
from typing import List, Optional

from src.domain.model.agent.plan import Plan, PlanNotFoundError
from src.domain.ports.repositories import PlanRepository

logger = logging.getLogger(__name__)


class GetPlanUseCase:
    """Use case for retrieving plan documents."""

    def __init__(self, plan_repository: PlanRepository):
        """
        Initialize the use case.

        Args:
            plan_repository: Repository for Plan entities
        """
        self._plan_repository = plan_repository

    async def execute(self, plan_id: str) -> Plan:
        """
        Get a plan by ID.

        Args:
            plan_id: The plan document ID

        Returns:
            The Plan entity

        Raises:
            PlanNotFoundError: If the plan doesn't exist
        """
        plan = await self._plan_repository.find_by_id(plan_id)
        if not plan:
            raise PlanNotFoundError(plan_id)

        logger.debug(f"Retrieved plan {plan_id}")
        return plan

    async def get_by_conversation(self, conversation_id: str) -> List[Plan]:
        """
        Get all plans for a conversation.

        Args:
            conversation_id: The conversation ID

        Returns:
            List of Plan entities
        """
        plans = await self._plan_repository.find_by_conversation_id(conversation_id)
        logger.debug(f"Retrieved {len(plans)} plans for conversation {conversation_id}")
        return plans

    async def get_active_plan(self, conversation_id: str) -> Optional[Plan]:
        """
        Get the active (non-archived) plan for a conversation.

        Args:
            conversation_id: The conversation ID

        Returns:
            The active Plan entity, or None if no active plan
        """
        plan = await self._plan_repository.find_active_by_conversation(conversation_id)
        if plan:
            logger.debug(f"Found active plan {plan.id} for conversation {conversation_id}")
        return plan
