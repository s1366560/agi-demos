"""Repository ports for agent-related entities.

This module defines the repository interfaces for agent domain entities:
- ConversationRepository: Manage conversations
- MessageRepository: Manage messages
- AgentExecutionRepository: Manage agent executions
"""

from abc import ABC, abstractmethod
from typing import List, Optional

from src.domain.model.agent import (
    AgentExecution,
    AgentExecutionEvent,
    Conversation,
    ConversationStatus,
    ExecutionCheckpoint,
    Message,
    ToolExecutionRecord,
)


class ConversationRepository(ABC):
    """
    Repository port for Conversation entities.

    Provides CRUD operations for conversations with project scoping.
    """

    @abstractmethod
    async def save(self, conversation: Conversation) -> None:
        """
        Save a conversation (create or update).

        Args:
            conversation: The conversation to save
        """
        pass

    @abstractmethod
    async def find_by_id(self, conversation_id: str) -> Optional[Conversation]:
        """
        Find a conversation by its ID.

        Args:
            conversation_id: The conversation ID

        Returns:
            The conversation if found, None otherwise
        """
        pass

    @abstractmethod
    async def list_by_project(
        self,
        project_id: str,
        status: ConversationStatus | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Conversation]:
        """
        List conversations for a project.

        Args:
            project_id: The project ID
            status: Optional status filter
            limit: Maximum number of results
            offset: Number of results to skip

        Returns:
            List of conversations
        """
        pass

    @abstractmethod
    async def list_by_user(
        self,
        user_id: str,
        project_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Conversation]:
        """
        List conversations for a user.

        Args:
            user_id: The user ID
            project_id: Optional project ID filter
            limit: Maximum number of results
            offset: Number of results to skip

        Returns:
            List of conversations
        """
        pass

    @abstractmethod
    async def delete(self, conversation_id: str) -> None:
        """
        Delete a conversation by ID.

        Args:
            conversation_id: The conversation ID to delete
        """
        pass

    @abstractmethod
    async def count_by_project(self, project_id: str) -> int:
        """
        Count conversations for a project.

        Args:
            project_id: The project ID

        Returns:
            Number of conversations
        """
        pass


class MessageRepository(ABC):
    """
    Repository port for Message entities.

    Provides CRUD operations for messages with conversation scoping.
    """

    @abstractmethod
    async def save(self, message: Message) -> None:
        """
        Save a message (create or update).

        Args:
            message: The message to save
        """
        pass

    @abstractmethod
    async def find_by_id(self, message_id: str) -> Optional[Message]:
        """
        Find a message by its ID.

        Args:
            message_id: The message ID

        Returns:
            The message if found, None otherwise
        """
        pass

    @abstractmethod
    async def list_by_conversation(
        self,
        conversation_id: str,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Message]:
        """
        List messages for a conversation.

        Args:
            conversation_id: The conversation ID
            limit: Maximum number of results
            offset: Number of results to skip

        Returns:
            List of messages in chronological order
        """
        pass

    @abstractmethod
    async def list_recent_by_project(
        self,
        project_id: str,
        limit: int = 10,
    ) -> List[Message]:
        """
        List recent messages across all conversations in a project.

        Args:
            project_id: The project ID
            limit: Maximum number of results

        Returns:
            List of recent messages
        """
        pass

    @abstractmethod
    async def count_by_conversation(self, conversation_id: str) -> int:
        """
        Count messages in a conversation.

        Args:
            conversation_id: The conversation ID

        Returns:
            Number of messages
        """
        pass

    @abstractmethod
    async def delete_by_conversation(self, conversation_id: str) -> None:
        """
        Delete all messages in a conversation.

        Args:
            conversation_id: The conversation ID
        """
        pass


class AgentExecutionRepository(ABC):
    """
    Repository port for AgentExecution entities.

    Provides CRUD operations for agent execution tracking.
    """

    @abstractmethod
    async def save(self, execution: AgentExecution) -> None:
        """
        Save an agent execution (create or update).

        Args:
            execution: The execution to save
        """
        pass

    @abstractmethod
    async def find_by_id(self, execution_id: str) -> Optional[AgentExecution]:
        """
        Find an execution by its ID.

        Args:
            execution_id: The execution ID

        Returns:
            The execution if found, None otherwise
        """
        pass

    @abstractmethod
    async def list_by_message(self, message_id: str) -> List[AgentExecution]:
        """
        List executions for a message.

        Args:
            message_id: The message ID

        Returns:
            List of executions in chronological order
        """
        pass

    @abstractmethod
    async def list_by_conversation(
        self,
        conversation_id: str,
        limit: int = 100,
    ) -> List[AgentExecution]:
        """
        List executions for a conversation.

        Args:
            conversation_id: The conversation ID
            limit: Maximum number of results

        Returns:
            List of executions in chronological order
        """
        pass

    @abstractmethod
    async def delete_by_conversation(self, conversation_id: str) -> None:
        """
        Delete all executions in a conversation.

        Args:
            conversation_id: The conversation ID
        """
        pass


class ToolExecutionRecordRepository(ABC):
    """
    Repository port for ToolExecutionRecord entities.

    Provides CRUD operations for tool execution history tracking.
    """

    @abstractmethod
    async def save(self, record: ToolExecutionRecord) -> None:
        """
        Save a tool execution record (create or update).

        Args:
            record: The tool execution record to save
        """
        pass

    @abstractmethod
    async def save_and_commit(self, record: ToolExecutionRecord) -> None:
        """
        Save a tool execution record and commit immediately.

        Args:
            record: The tool execution record to save
        """
        pass

    @abstractmethod
    async def find_by_id(self, record_id: str) -> Optional[ToolExecutionRecord]:
        """
        Find a tool execution record by its ID.

        Args:
            record_id: The record ID

        Returns:
            The record if found, None otherwise
        """
        pass

    @abstractmethod
    async def find_by_call_id(self, call_id: str) -> Optional[ToolExecutionRecord]:
        """
        Find a tool execution record by its call ID.

        Args:
            call_id: The tool call ID

        Returns:
            The record if found, None otherwise
        """
        pass

    @abstractmethod
    async def list_by_message(
        self,
        message_id: str,
        limit: int = 100,
    ) -> List[ToolExecutionRecord]:
        """
        List tool executions for a message.

        Args:
            message_id: The message ID
            limit: Maximum number of results

        Returns:
            List of tool executions in sequence order
        """
        pass

    @abstractmethod
    async def list_by_conversation(
        self,
        conversation_id: str,
        limit: int = 100,
    ) -> List[ToolExecutionRecord]:
        """
        List tool executions for a conversation.

        Args:
            conversation_id: The conversation ID
            limit: Maximum number of results

        Returns:
            List of tool executions in chronological order
        """
        pass

    @abstractmethod
    async def delete_by_conversation(self, conversation_id: str) -> None:
        """
        Delete all tool execution records in a conversation.

        Args:
            conversation_id: The conversation ID
        """
        pass

    @abstractmethod
    async def update_status(
        self,
        call_id: str,
        status: str,
        output: Optional[str] = None,
        error: Optional[str] = None,
        duration_ms: Optional[int] = None,
    ) -> None:
        """
        Update the status of a tool execution record.

        Args:
            call_id: The tool call ID
            status: New status (success, failed)
            output: Tool output (if successful)
            error: Error message (if failed)
            duration_ms: Execution duration in milliseconds
        """
        pass


class AgentExecutionEventRepository(ABC):
    """
    Repository port for AgentExecutionEvent entities.

    Provides CRUD operations for SSE event persistence and replay.
    """

    @abstractmethod
    async def save(self, event: AgentExecutionEvent) -> None:
        """
        Save an agent execution event.

        Args:
            event: The event to save
        """
        pass

    @abstractmethod
    async def save_and_commit(self, event: AgentExecutionEvent) -> None:
        """
        Save an event and commit immediately.

        Args:
            event: The event to save
        """
        pass

    @abstractmethod
    async def save_batch(self, events: List[AgentExecutionEvent]) -> None:
        """
        Save multiple events efficiently.

        Args:
            events: List of events to save
        """
        pass

    @abstractmethod
    async def get_events(
        self,
        conversation_id: str,
        from_sequence: int = 0,
        limit: int = 1000,
    ) -> List[AgentExecutionEvent]:
        """
        Get events for a conversation starting from a sequence number.

        Args:
            conversation_id: The conversation ID
            from_sequence: Starting sequence number (inclusive)
            limit: Maximum number of events to return

        Returns:
            List of events in sequence order
        """
        pass

    @abstractmethod
    async def get_last_sequence(self, conversation_id: str) -> int:
        """
        Get the last sequence number for a conversation.

        Args:
            conversation_id: The conversation ID

        Returns:
            The last sequence number, or 0 if no events exist
        """
        pass

    @abstractmethod
    async def get_events_by_message(
        self,
        message_id: str,
    ) -> List[AgentExecutionEvent]:
        """
        Get all events for a specific message.

        Args:
            message_id: The message ID

        Returns:
            List of events in sequence order
        """
        pass

    @abstractmethod
    async def delete_by_conversation(self, conversation_id: str) -> None:
        """
        Delete all events for a conversation.

        Args:
            conversation_id: The conversation ID
        """
        pass

    @abstractmethod
    async def list_by_conversation(
        self,
        conversation_id: str,
        limit: int = 1000,
    ) -> List[AgentExecutionEvent]:
        """
        List all events for a conversation in sequence order.

        This is an alias for get_events() with from_sequence=0 for convenience.

        Args:
            conversation_id: The conversation ID
            limit: Maximum number of events to return

        Returns:
            List of events in sequence order
        """
        pass

    @abstractmethod
    async def get_message_events(
        self,
        conversation_id: str,
        limit: int = 50,
    ) -> List[AgentExecutionEvent]:
        """
        Get message events (user_message + assistant_message) for LLM context.

        This method filters events to only return user and assistant messages,
        ordered by sequence number for building conversation context.

        Args:
            conversation_id: The conversation ID
            limit: Maximum number of messages to return (default 50)

        Returns:
            List of message events in sequence order (oldest first)
        """
        pass

    @abstractmethod
    async def count_messages(self, conversation_id: str) -> int:
        """
        Count message events in a conversation.

        Counts only user_message and assistant_message events.

        Args:
            conversation_id: The conversation ID

        Returns:
            Number of message events
        """
        pass


class ExecutionCheckpointRepository(ABC):
    """
    Repository port for ExecutionCheckpoint entities.

    Provides CRUD operations for execution checkpoint persistence
    and recovery support.
    """

    @abstractmethod
    async def save(self, checkpoint: ExecutionCheckpoint) -> None:
        """
        Save an execution checkpoint.

        Args:
            checkpoint: The checkpoint to save
        """
        pass

    @abstractmethod
    async def save_and_commit(self, checkpoint: ExecutionCheckpoint) -> None:
        """
        Save a checkpoint and commit immediately.

        Args:
            checkpoint: The checkpoint to save
        """
        pass

    @abstractmethod
    async def get_latest(
        self,
        conversation_id: str,
        message_id: Optional[str] = None,
    ) -> Optional[ExecutionCheckpoint]:
        """
        Get the latest checkpoint for a conversation.

        Args:
            conversation_id: The conversation ID
            message_id: Optional message ID to filter by

        Returns:
            The latest checkpoint if found, None otherwise
        """
        pass

    @abstractmethod
    async def get_by_type(
        self,
        conversation_id: str,
        checkpoint_type: str,
        limit: int = 10,
    ) -> List[ExecutionCheckpoint]:
        """
        Get checkpoints of a specific type for a conversation.

        Args:
            conversation_id: The conversation ID
            checkpoint_type: The type of checkpoint
            limit: Maximum number of checkpoints to return

        Returns:
            List of checkpoints in descending order (newest first)
        """
        pass

    @abstractmethod
    async def delete_by_conversation(self, conversation_id: str) -> None:
        """
        Delete all checkpoints for a conversation.

        Args:
            conversation_id: The conversation ID
        """
        pass
