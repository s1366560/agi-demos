"""Execution Resume Service - Agent session recovery.

Provides functionality to resume agent execution from a checkpoint
when execution was interrupted due to failure, timeout, or disconnection.
"""

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from src.domain.model.agent.execution.execution_checkpoint import (
    ExecutionCheckpoint,
)
from src.domain.ports.repositories.agent_repository import (
    ExecutionCheckpointRepository,
)

logger = logging.getLogger(__name__)


@dataclass
class ResumeResult:
    """Result of a resume operation."""

    success: bool
    conversation_id: str
    checkpoint_id: str
    step_number: int
    message: str
    resumed_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    error: str | None = None


@dataclass
class ResumeContext:
    """Context needed to resume execution."""

    conversation_id: str
    project_id: str
    tenant_id: str
    user_id: str
    checkpoint: ExecutionCheckpoint
    pending_message: str | None = None


class ExecutionResumeService:
    """
    Service for resuming agent execution from checkpoints.

    This service handles the recovery of agent sessions that were
    interrupted during execution. It:
    1. Retrieves the latest checkpoint for a conversation
    2. Extracts the execution state
    3. Prepares context for resuming execution
    """

    def __init__(
        self,
        checkpoint_repo: ExecutionCheckpointRepository,
    ) -> None:
        """Initialize the resume service.

        Args:
            checkpoint_repo: Repository for accessing checkpoints
        """
        self._checkpoint_repo = checkpoint_repo

    async def get_resume_context(
        self,
        conversation_id: str,
    ) -> ResumeContext | None:
        """Get the context needed to resume execution.

        Args:
            conversation_id: Conversation to resume

        Returns:
            ResumeContext if resumable, None otherwise
        """
        checkpoint = await self._checkpoint_repo.get_latest(conversation_id)
        if not checkpoint:
            logger.warning(f"No checkpoint found for conversation {conversation_id}")
            return None

        # Extract context from checkpoint
        state = checkpoint.execution_state

        return ResumeContext(
            conversation_id=conversation_id,
            project_id=state.get("project_id", ""),
            tenant_id=state.get("tenant_id", ""),
            user_id=state.get("user_id", ""),
            checkpoint=checkpoint,
            pending_message=state.get("pending_user_message"),
        )

    async def can_resume(self, conversation_id: str) -> bool:
        """Check if a conversation can be resumed.

        Args:
            conversation_id: Conversation to check

        Returns:
            True if the conversation has a resumable checkpoint
        """
        checkpoint = await self._checkpoint_repo.get_latest(conversation_id)
        if not checkpoint:
            return False

        # Check if checkpoint has required state
        state = checkpoint.execution_state
        required_keys = ["project_id", "tenant_id", "user_id"]
        return all(key in state for key in required_keys)

    async def prepare_resume_request(
        self,
        conversation_id: str,
        override_message: str | None = None,
    ) -> dict[str, Any] | None:
        """Prepare a request dictionary for resuming execution.

        This method extracts all necessary information from the checkpoint
        to create a request that can be used to resume the agent.

        Args:
            conversation_id: Conversation to resume
            override_message: Optional message to use instead of the pending one

        Returns:
            Request dictionary for agent execution, or None if not resumable
        """
        context = await self.get_resume_context(conversation_id)
        if not context:
            return None

        state = context.checkpoint.execution_state

        # Build the resume request
        request = {
            "conversation_id": conversation_id,
            "project_id": context.project_id,
            "tenant_id": context.tenant_id,
            "user_id": context.user_id,
            "user_message": override_message or context.pending_message or "[Resuming execution]",
            "conversation_context": state.get("conversation_context", []),
            "message_id": context.checkpoint.message_id,
            "resume_from_checkpoint": True,
            "checkpoint_id": context.checkpoint.id,
            "step_number": context.checkpoint.step_number,
        }

        return request

    async def mark_resumed(
        self,
        conversation_id: str,
        checkpoint_id: str,
    ) -> None:
        """Mark a checkpoint as having been resumed.

        Creates a new checkpoint marking the resume event.

        Args:
            conversation_id: Conversation that was resumed
            checkpoint_id: Checkpoint that was resumed from
        """
        resume_checkpoint = ExecutionCheckpoint(
            conversation_id=conversation_id,
            message_id="",
            checkpoint_type="resumed",
            execution_state={
                "resumed_from_checkpoint": checkpoint_id,
                "resumed_at": datetime.now(UTC).isoformat(),
            },
            step_number=None,
        )
        await self._checkpoint_repo.save(resume_checkpoint)
        logger.info(
            f"Marked checkpoint {checkpoint_id} as resumed for conversation {conversation_id}"
        )
