"""Repository port for PlanExecution entities.

This module defines the repository interface for unified plan execution persistence.
"""

from abc import ABC, abstractmethod
from typing import Optional

from src.domain.model.agent.plan_execution import ExecutionStatus, PlanExecution


class PlanExecutionRepository(ABC):
    """Repository for PlanExecution entities.

    Provides CRUD operations for unified plan execution with conversation scoping.
    """

    @abstractmethod
    async def save(self, execution: PlanExecution) -> PlanExecution:
        """Save or update a plan execution.

        Args:
            execution: The plan execution to save

        Returns:
            The saved plan execution
        """
        ...

    @abstractmethod
    async def find_by_id(self, execution_id: str) -> Optional[PlanExecution]:
        """Find a plan execution by its ID.

        Args:
            execution_id: The execution ID

        Returns:
            The plan execution if found, None otherwise
        """
        ...

    @abstractmethod
    async def find_by_plan_id(self, plan_id: str) -> list[PlanExecution]:
        """Find all executions for a plan.

        Args:
            plan_id: The plan ID

        Returns:
            List of plan executions
        """
        ...

    @abstractmethod
    async def find_by_conversation(
        self,
        conversation_id: str,
        status: Optional[ExecutionStatus] = None,
    ) -> list[PlanExecution]:
        """Find executions for a conversation.

        Args:
            conversation_id: The conversation ID
            status: Optional status filter

        Returns:
            List of plan executions
        """
        ...

    @abstractmethod
    async def find_active_by_conversation(
        self,
        conversation_id: str,
    ) -> Optional[PlanExecution]:
        """Find active (running/paused) execution for a conversation.

        Args:
            conversation_id: The conversation ID

        Returns:
            The active plan execution if found, None otherwise
        """
        ...

    @abstractmethod
    async def update_status(
        self,
        execution_id: str,
        status: ExecutionStatus,
    ) -> Optional[PlanExecution]:
        """Update execution status.

        Args:
            execution_id: The execution ID
            status: New status

        Returns:
            Updated plan execution if found, None otherwise
        """
        ...

    @abstractmethod
    async def update_step(
        self,
        execution_id: str,
        step_index: int,
        step_data: dict,
    ) -> Optional[PlanExecution]:
        """Update a step within an execution.

        Args:
            execution_id: The execution ID
            step_index: Index of the step to update
            step_data: Updated step data

        Returns:
            Updated plan execution if found, None otherwise
        """
        ...

    @abstractmethod
    async def delete(self, execution_id: str) -> bool:
        """Delete an execution.

        Args:
            execution_id: The execution ID to delete

        Returns:
            True if deleted, False if not found
        """
        ...
