"""Conversation CRUD operations extracted from AgentService."""

import asyncio
import logging
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any, Dict, Optional

from src.domain.llm_providers.llm_types import LLMClient, Message as LLMMessage
from src.domain.model.agent import (
    AgentExecutionEvent,
    Conversation,
    ConversationStatus,
)
from src.domain.ports.repositories.agent_repository import (
    AgentExecutionEventRepository,
    AgentExecutionRepository,
    ConversationRepository,
    ExecutionCheckpointRepository,
    ToolExecutionRecordRepository,
)

if TYPE_CHECKING:
    from src.domain.ports.repositories.work_plan_repository import WorkPlanRepositoryPort

logger = logging.getLogger(__name__)


class ConversationManager:
    """Handles conversation CRUD operations."""

    def __init__(
        self,
        conversation_repo: ConversationRepository,
        execution_repo: AgentExecutionRepository,
        agent_execution_event_repo: Optional[AgentExecutionEventRepository] = None,
        tool_execution_record_repo: Optional[ToolExecutionRecordRepository] = None,
        execution_checkpoint_repo: Optional[ExecutionCheckpointRepository] = None,
        work_plan_repo: "Optional[WorkPlanRepositoryPort]" = None,
    ) -> None:
        self._conversation_repo = conversation_repo
        self._execution_repo = execution_repo
        self._agent_execution_event_repo = agent_execution_event_repo
        self._tool_execution_record_repo = tool_execution_record_repo
        self._execution_checkpoint_repo = execution_checkpoint_repo
        self._work_plan_repo = work_plan_repo

    async def create_conversation(
        self,
        project_id: str,
        user_id: str,
        tenant_id: str,
        title: str | None = None,
        agent_config: Dict[str, Any] | None = None,
    ) -> Conversation:
        """Create a new conversation."""
        conversation = Conversation(
            id=str(uuid.uuid4()),
            project_id=project_id,
            tenant_id=tenant_id,
            user_id=user_id,
            title=title or "New Conversation",
            status=ConversationStatus.ACTIVE,
            agent_config=agent_config or {},
            metadata={"created_at": datetime.utcnow().isoformat()},
            message_count=0,
            created_at=datetime.utcnow(),
        )

        await self._conversation_repo.save(conversation)
        logger.info(f"Created conversation {conversation.id} for project {project_id}")
        return conversation

    async def get_conversation(
        self, conversation_id: str, project_id: str, user_id: str
    ) -> Conversation | None:
        """Get a conversation by ID."""
        conversation = await self._conversation_repo.find_by_id(conversation_id)
        if not conversation:
            return None
        if conversation.project_id != project_id or conversation.user_id != user_id:
            logger.warning(
                f"Unauthorized access attempt to conversation {conversation_id} "
                f"by user {user_id} in project {project_id}"
            )
            return None
        return conversation

    async def list_conversations(
        self,
        project_id: str,
        user_id: str,
        limit: int = 50,
        status: ConversationStatus | None = None,
    ) -> list[Conversation]:
        """List conversations for a project."""
        return await self._conversation_repo.list_by_project(
            project_id=project_id, limit=limit, status=status
        )

    async def delete_conversation(
        self, conversation_id: str, project_id: str, user_id: str
    ) -> bool:
        """Delete a conversation and all its messages."""
        conversation = await self._conversation_repo.find_by_id(conversation_id)
        if not conversation:
            logger.warning(f"Attempted to delete non-existent conversation {conversation_id}")
            return False

        if conversation.project_id != project_id or conversation.user_id != user_id:
            logger.warning(
                f"Unauthorized delete attempt on conversation {conversation_id} "
                f"by user {user_id} in project {project_id}"
            )
            return False

        if self._tool_execution_record_repo:
            await self._tool_execution_record_repo.delete_by_conversation(conversation_id)

        if self._agent_execution_event_repo:
            await self._agent_execution_event_repo.delete_by_conversation(conversation_id)

        if self._execution_checkpoint_repo:
            await self._execution_checkpoint_repo.delete_by_conversation(conversation_id)

        if self._work_plan_repo:
            await self._work_plan_repo.delete_by_conversation(conversation_id)

        await self._execution_repo.delete_by_conversation(conversation_id)

        await self._conversation_repo.delete(conversation_id)

        logger.info(f"Deleted conversation {conversation_id}")
        return True

    async def update_conversation_title(
        self, conversation_id: str, project_id: str, user_id: str, title: str
    ) -> Conversation | None:
        """Update conversation title."""
        logger.info(f"[update_conversation_title] START: id={conversation_id}, title='{title}'")
        conversation = await self._conversation_repo.find_by_id(conversation_id)
        if not conversation:
            logger.warning(f"Attempted to update non-existent conversation {conversation_id}")
            return None

        logger.info(
            f"[update_conversation_title] Found conversation: project_id={conversation.project_id}, user_id={conversation.user_id}, current_title='{conversation.title}'"
        )
        logger.info(
            f"[update_conversation_title] Authorization check: expected project_id={project_id}, user_id={user_id}"
        )

        if conversation.project_id != project_id or conversation.user_id != user_id:
            logger.warning(
                f"Unauthorized title update attempt on conversation {conversation_id} "
                f"by user {user_id} in project {project_id}"
            )
            return None

        logger.info(f"[update_conversation_title] Calling conversation.update_title('{title}')")
        conversation.update_title(title)
        logger.info("[update_conversation_title] Title updated in domain model, now saving...")
        await self._conversation_repo.save_and_commit(conversation)

        logger.info(f"Updated title for conversation {conversation_id} to: {title}")
        return conversation

    async def generate_conversation_title(self, first_message: str, llm: LLMClient) -> str:
        """Generate a friendly, concise title for a conversation."""
        prompt = f"""Generate a short, friendly title (max 50 characters) for a conversation that starts with this message:

"{first_message[:200]}"

Guidelines:
- Be concise and descriptive
- Use the user's language (English, Chinese, etc.)
- Focus on the main topic or question
- Maximum 50 characters
- Return ONLY the title, no explanation

Title:"""

        max_retries = 3
        base_delay = 1.0

        for attempt in range(max_retries):
            try:
                response = await llm.ainvoke(
                    [
                        LLMMessage.system(
                            "You are a helpful assistant that generates concise conversation titles."
                        ),
                        LLMMessage.user(prompt),
                    ]
                )

                title = response.content.strip().strip('"').strip("'")

                if len(title) > 50:
                    title = title[:47] + "..."
                if not title:
                    title = "New Conversation"

                logger.info(f"Generated conversation title: {title}")
                return title

            except Exception as e:
                logger.warning(
                    f"[generate_conversation_title] Attempt {attempt + 1}/{max_retries} failed: {e}"
                )

                if attempt < max_retries - 1:
                    delay = base_delay * (2**attempt)
                    logger.info(f"Retrying in {delay}s...")
                    await asyncio.sleep(delay)
                else:
                    logger.error(f"All {max_retries} retries exhausted for title generation")
                    return self._generate_fallback_title(first_message)

        return "New Conversation"

    def _generate_fallback_title(self, first_message: str) -> str:
        """Generate a fallback title from the first message when LLM fails."""
        content = first_message.strip()

        if len(content) > 40:
            truncated = content[:40]
            last_space = truncated.rfind(" ")
            if last_space > 20:
                truncated = truncated[:last_space]
            content = truncated + "..."

        logger.info(f"Using fallback title: '{content}'")
        return content or "New Conversation"

    async def get_conversation_messages(
        self,
        conversation_id: str,
        project_id: str,
        user_id: str,
        limit: int = 100,
    ) -> list[AgentExecutionEvent]:
        """Get all message events in a conversation."""
        conversation = await self._conversation_repo.find_by_id(conversation_id)
        if not conversation:
            logger.warning(
                f"Attempted to get messages for non-existent conversation {conversation_id}"
            )
            return []

        if conversation.project_id != project_id or conversation.user_id != user_id:
            logger.warning(
                f"Unauthorized message access attempt on conversation {conversation_id} "
                f"by user {user_id} in project {project_id}"
            )
            return []

        return await self._agent_execution_event_repo.get_message_events(
            conversation_id=conversation_id, limit=limit
        )

    async def get_execution_history(
        self,
        conversation_id: str,
        project_id: str,
        user_id: str,
        limit: int = 50,
    ) -> list[Dict[str, Any]]:
        """Get the execution history for a conversation."""
        conversation = await self._conversation_repo.find_by_id(conversation_id)
        if not conversation:
            logger.warning(
                f"Attempted to get executions for non-existent conversation {conversation_id}"
            )
            raise ValueError(f"Conversation {conversation_id} not found")

        if conversation.project_id != project_id or conversation.user_id != user_id:
            logger.warning(
                f"Unauthorized execution history access attempt on conversation {conversation_id} "
                f"by user {user_id} in project {project_id}"
            )
            raise ValueError("You do not have permission to access this conversation")

        executions = await self._execution_repo.list_by_conversation(
            conversation_id=conversation_id, limit=limit
        )

        return [
            {
                "id": exec.id,
                "message_id": exec.message_id,
                "status": exec.status.value if exec.status else None,
                "started_at": exec.started_at.isoformat() if exec.started_at else None,
                "completed_at": exec.completed_at.isoformat() if exec.completed_at else None,
                "thought": exec.thought,
                "action": exec.action,
                "tool_name": exec.tool_name,
                "tool_input": exec.tool_input,
                "tool_output": exec.tool_output,
                "observation": exec.observation,
                "metadata": exec.metadata,
            }
            for exec in executions
        ]

    async def get_conversation_context(
        self, conversation_id: str, max_messages: int = 50
    ) -> list[Dict[str, Any]]:
        """Get conversation context for agent processing."""
        message_events = await self._agent_execution_event_repo.get_message_events(
            conversation_id=conversation_id, limit=max_messages
        )

        return [
            {
                "role": event.event_data.get("role", "user"),
                "content": event.event_data.get("content", ""),
            }
            for event in message_events
        ]
