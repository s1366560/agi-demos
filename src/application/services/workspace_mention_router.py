from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from src.domain.model.workspace.workspace_agent import WorkspaceAgent
from src.domain.model.workspace.workspace_message import (
    MessageSenderType,
    WorkspaceMessage,
)
from src.domain.ports.repositories.workspace.workspace_agent_repository import (
    WorkspaceAgentRepository,
)

logger = logging.getLogger(__name__)

_background_tasks: set[asyncio.Task[Any]] = set()


class WorkspaceMentionRouter:
    def __init__(
        self,
        agent_repo_factory: Callable[..., WorkspaceAgentRepository],
        agent_service_factory: Callable[..., Any],
        message_service_factory: Callable[..., Any],
        conversation_repo_factory: Callable[..., Any],
        db_session_factory: Callable[..., Any],
    ) -> None:
        self._agent_repo_factory = agent_repo_factory
        self._agent_service_factory = agent_service_factory
        self._message_service_factory = message_service_factory
        self._conversation_repo_factory = conversation_repo_factory
        self._db_session_factory = db_session_factory

    def fire_and_forget(
        self,
        workspace_id: str,
        message: WorkspaceMessage,
        tenant_id: str,
        project_id: str,
        event_publisher: (Callable[[str, str, dict[str, Any]], Awaitable[None]] | None) = None,
    ) -> None:
        """Schedule mention routing as a background task (non-blocking)."""
        task = asyncio.create_task(
            self.route_mentions(
                workspace_id=workspace_id,
                message=message,
                tenant_id=tenant_id,
                project_id=project_id,
                event_publisher=event_publisher,
            )
        )
        _background_tasks.add(task)
        task.add_done_callback(_background_tasks.discard)

    async def route_mentions(
        self,
        workspace_id: str,
        message: WorkspaceMessage,
        tenant_id: str,
        project_id: str,
        event_publisher: (Callable[[str, str, dict[str, Any]], Awaitable[None]] | None) = None,
    ) -> None:
        """Route mentions to agents sequentially."""
        if not message.mentions:
            return

        async with self._db_session_factory() as db:
            agent_repo = self._agent_repo_factory(db)
            agents = await agent_repo.find_by_workspace(workspace_id, active_only=True)

        agent_by_id: dict[str, WorkspaceAgent] = {a.agent_id: a for a in agents}

        mentioned_agents = [agent_by_id[mid] for mid in message.mentions if mid in agent_by_id]

        if not mentioned_agents:
            return

        for agent in mentioned_agents:
            try:
                await self._trigger_agent(
                    workspace_id=workspace_id,
                    agent=agent,
                    message=message,
                    tenant_id=tenant_id,
                    project_id=project_id,
                    event_publisher=event_publisher,
                )
            except Exception:
                logger.exception(
                    "Failed to trigger agent %s for mention in workspace %s",
                    agent.agent_id,
                    workspace_id,
                )
                await self._post_error_message(
                    workspace_id=workspace_id,
                    agent=agent,
                    original_message=message,
                    event_publisher=event_publisher,
                )

    async def _trigger_agent(
        self,
        workspace_id: str,
        agent: WorkspaceAgent,
        message: WorkspaceMessage,
        tenant_id: str,
        project_id: str,
        event_publisher: (Callable[[str, str, dict[str, Any]], Awaitable[None]] | None) = None,
    ) -> None:
        """Trigger a single agent and post its response back to workspace chat."""
        from src.configuration.factories import create_llm_client

        agent_name = agent.display_name or agent.agent_id

        logger.info(
            "Triggering agent %s (%s) for mention in workspace %s",
            agent_name,
            agent.agent_id,
            workspace_id,
        )

        sender_name = message.metadata.get("sender_name", "someone")
        user_prompt = f"[Workspace Chat] {sender_name} mentioned you:\n\n{message.content}"

        conversation_id = self.workspace_conversation_id(workspace_id, agent.agent_id)

        async with self._db_session_factory() as db:
            conversation_repo = self._conversation_repo_factory(db)
            existing = await conversation_repo.find_by_id(conversation_id)

            if existing is None:
                from datetime import UTC, datetime

                from src.domain.model.agent import Conversation, ConversationStatus

                conversation = Conversation(
                    id=conversation_id,
                    project_id=project_id,
                    tenant_id=tenant_id,
                    user_id=f"workspace:{workspace_id}",
                    title=f"Workspace Chat - {agent_name}",
                    status=ConversationStatus.ACTIVE,
                    agent_config={},
                    metadata={
                        "workspace_id": workspace_id,
                        "agent_id": agent.agent_id,
                        "created_at": datetime.now(UTC).isoformat(),
                    },
                    message_count=0,
                    created_at=datetime.now(UTC),
                )
                await conversation_repo.save(conversation)
                await db.commit()

        llm = await create_llm_client(tenant_id)

        async with self._db_session_factory() as db:
            container = self._agent_service_factory(db, llm)
            agent_service = container

            final_content = ""
            has_error = False

            async for event in agent_service.stream_chat_v2(
                conversation_id=conversation_id,
                user_message=user_prompt,
                project_id=project_id,
                user_id=f"workspace:{workspace_id}",
                tenant_id=tenant_id,
                agent_id=agent.agent_id,
            ):
                event_type = event.get("type")
                if event_type == "complete":
                    final_content = event.get("data", {}).get("content", "")
                elif event_type == "error":
                    has_error = True
                    final_content = event.get("data", {}).get(
                        "message", "An error occurred while processing your request."
                    )

        if has_error:
            await self._post_error_message(
                workspace_id=workspace_id,
                agent=agent,
                original_message=message,
                error_detail=final_content,
                event_publisher=event_publisher,
            )
            return

        if final_content:
            await self._post_agent_response(
                workspace_id=workspace_id,
                agent=agent,
                content=final_content,
                parent_message_id=message.id,
                event_publisher=event_publisher,
            )

    async def _post_agent_response(
        self,
        workspace_id: str,
        agent: WorkspaceAgent,
        content: str,
        parent_message_id: str | None = None,
        event_publisher: (Callable[[str, str, dict[str, Any]], Awaitable[None]] | None) = None,
    ) -> None:
        """Post an agent's response as a workspace chat message."""
        agent_name = agent.display_name or agent.agent_id

        async with self._db_session_factory() as db:
            message_service = self._message_service_factory(db, event_publisher)
            await message_service.send_message(
                workspace_id=workspace_id,
                sender_id=agent.agent_id,
                sender_type=MessageSenderType.AGENT,
                sender_name=agent_name,
                content=content,
                parent_message_id=parent_message_id,
            )
            await db.commit()

    async def _post_error_message(
        self,
        workspace_id: str,
        agent: WorkspaceAgent,
        original_message: WorkspaceMessage,
        error_detail: str | None = None,
        event_publisher: (Callable[[str, str, dict[str, Any]], Awaitable[None]] | None) = None,
    ) -> None:
        """Post an error message to workspace chat when agent trigger fails."""
        agent_name = agent.display_name or agent.agent_id
        detail = error_detail or "An unexpected error occurred."
        error_content = f"[Error] {agent_name} could not process your request: {detail}"

        await self._post_agent_response(
            workspace_id=workspace_id,
            agent=agent,
            content=error_content,
            parent_message_id=original_message.id,
            event_publisher=event_publisher,
        )

    @staticmethod
    def workspace_conversation_id(workspace_id: str, agent_id: str) -> str:
        """Generate a deterministic conversation ID for workspace+agent pair."""
        return str(uuid.uuid5(uuid.NAMESPACE_DNS, f"workspace:{workspace_id}:agent:{agent_id}"))
