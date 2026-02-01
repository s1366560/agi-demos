"""
Agent Execution Repository Port - Interface for agent execution persistence.

This port defines the contract for storing and retrieving agent execution status.
"""

from abc import ABC, abstractmethod
from typing import Optional

from src.domain.model.agent.execution_status import AgentExecution, AgentExecutionStatus


class AgentExecutionRepositoryPort(ABC):
    """
    Abstract port for agent execution persistence.

    This repository tracks the execution status of agent responses,
    enabling recovery after page refresh.
    """

    @abstractmethod
    async def create(self, execution: AgentExecution) -> AgentExecution:
        """
        Create a new execution record.

        Args:
            execution: The execution to create

        Returns:
            The created execution with any generated fields
        """
        pass

    @abstractmethod
    async def get_by_id(self, execution_id: str) -> Optional[AgentExecution]:
        """
        Get execution by ID.

        Args:
            execution_id: The execution ID (usually same as message_id)

        Returns:
            The execution if found, None otherwise
        """
        pass

    @abstractmethod
    async def get_by_message_id(
        self,
        message_id: str,
        conversation_id: Optional[str] = None,
    ) -> Optional[AgentExecution]:
        """
        Get execution by message ID.

        Args:
            message_id: The message ID
            conversation_id: Optional conversation ID for filtering

        Returns:
            The execution if found, None otherwise
        """
        pass

    @abstractmethod
    async def get_running_by_conversation(
        self,
        conversation_id: str,
    ) -> Optional[AgentExecution]:
        """
        Get the currently running execution for a conversation.

        A conversation can only have one running execution at a time.

        Args:
            conversation_id: The conversation ID

        Returns:
            The running execution if found, None otherwise
        """
        pass

    @abstractmethod
    async def update_status(
        self,
        execution_id: str,
        status: AgentExecutionStatus,
        error_message: Optional[str] = None,
    ) -> Optional[AgentExecution]:
        """
        Update execution status.

        Args:
            execution_id: The execution ID
            status: New status
            error_message: Optional error message (for FAILED status)

        Returns:
            The updated execution if found, None otherwise
        """
        pass

    @abstractmethod
    async def update_sequence(
        self,
        execution_id: str,
        sequence: int,
    ) -> Optional[AgentExecution]:
        """
        Update the last event sequence number.

        Args:
            execution_id: The execution ID
            sequence: The new sequence number

        Returns:
            The updated execution if found, None otherwise
        """
        pass

    @abstractmethod
    async def delete(self, execution_id: str) -> bool:
        """
        Delete an execution record.

        Args:
            execution_id: The execution ID

        Returns:
            True if deleted, False if not found
        """
        pass
