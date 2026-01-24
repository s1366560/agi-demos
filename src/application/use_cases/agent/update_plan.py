"""Update Plan use case.

This use case handles updating plan document content and metadata.
"""

import logging
from typing import Any, Dict, List, Optional

from src.domain.model.agent.plan import InvalidPlanStateError, Plan, PlanNotFoundError
from src.domain.ports.repositories import PlanRepository

logger = logging.getLogger(__name__)


class UpdatePlanUseCase:
    """Use case for updating plan content."""

    def __init__(self, plan_repository: PlanRepository):
        """
        Initialize the use case.

        Args:
            plan_repository: Repository for Plan entities
        """
        self._plan_repository = plan_repository

    async def execute(
        self,
        plan_id: str,
        content: Optional[str] = None,
        title: Optional[str] = None,
        explored_files: Optional[List[str]] = None,
        critical_files: Optional[List[Dict[str, str]]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Plan:
        """
        Execute the use case.

        Args:
            plan_id: The plan document ID to update
            content: New content (Markdown format)
            title: New title for the plan
            explored_files: List of file paths that were explored
            critical_files: List of critical files with modification types
            metadata: Additional metadata to add

        Returns:
            The updated Plan entity

        Raises:
            PlanNotFoundError: If the plan doesn't exist
            InvalidPlanStateError: If the plan is not editable
        """
        # Fetch the plan
        plan = await self._plan_repository.find_by_id(plan_id)
        if not plan:
            raise PlanNotFoundError(plan_id)

        # Check if plan is editable
        if not plan.is_editable:
            raise InvalidPlanStateError(plan.status, "update")

        old_version = plan.version

        # Update title if provided
        if title is not None:
            plan.title = title

        # Update content if provided
        if content is not None:
            plan.update_content(content)

        # Add explored files
        if explored_files:
            for file_path in explored_files:
                plan.add_explored_file(file_path)

        # Add critical files
        if critical_files:
            for file_info in critical_files:
                path = file_info.get("path", "")
                mod_type = file_info.get("type", "modify")
                if path:
                    plan.add_critical_file(path, mod_type)

        # Add additional metadata
        if metadata:
            for key, value in metadata.items():
                plan.add_metadata(key, value)

        # Persist changes
        await self._plan_repository.save(plan)

        logger.info(f"Updated plan {plan_id}: version {old_version} -> {plan.version}")

        return plan
