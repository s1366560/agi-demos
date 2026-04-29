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
from src.infrastructure.adapters.secondary.persistence.sql_workspace_task_repository import (
    SqlWorkspaceTaskRepository,
)
from src.infrastructure.agent.workspace.runtime_role_contract import (
    WORKSPACE_ROLE_LEADER,
    WORKSPACE_SESSION_ROLE_KEY,
    WORKSPACE_TOOL_MODE_KEY,
    WORKSPACE_TOOL_MODE_TASK_LEDGER_ONLY,
    WORKSPACE_TURN_TYPE_KEY,
    WORKSPACE_TURN_TYPE_LEADER_REPLAN,
)
from src.infrastructure.agent.workspace.workspace_metadata_keys import (
    REMEDIATION_STATUS,
    ROOT_GOAL_TASK_ID,
    TASK_ROLE,
)

logger = logging.getLogger(__name__)

_background_tasks: set[asyncio.Task[Any]] = set()
_MAX_MENTION_CHAIN_DEPTH = 3


async def _resolve_workspace_authority_context(
    db_session_factory: Callable[..., Any],
    *,
    workspace_id: str,
    conversation_scope: str | None,
) -> dict[str, Any] | None:
    async with db_session_factory() as meta_db:
        try:
            objective_id: str | None = None
            if conversation_scope and conversation_scope.startswith("objective:"):
                objective_id = conversation_scope.split(":", 1)[1].strip() or None
            root_goal_task_id: str | None = None
            task_repo = SqlWorkspaceTaskRepository(meta_db)
            if objective_id:
                root_task = await task_repo.find_root_by_objective_id(workspace_id, objective_id)
                if root_task is not None:
                    root_goal_task_id = root_task.id
            if root_goal_task_id is None:
                tasks = await task_repo.find_by_workspace(
                    workspace_id=workspace_id,
                    limit=100,
                    offset=0,
                )
                root_tasks = [
                    task
                    for task in tasks
                    if task.metadata.get(TASK_ROLE) == "goal_root"
                    and task.archived_at is None
                    and getattr(task.status, "value", task.status) != "done"
                ]
                if len(root_tasks) == 1:
                    root_goal_task_id = root_tasks[0].id
        except Exception:
            logger.warning(
                "Workspace authority context resolution failed",
                exc_info=True,
                extra={"workspace_id": workspace_id, "conversation_scope": conversation_scope},
            )
            return None
        if root_goal_task_id:
            workspace_binding = {
                "workspace_id": workspace_id,
                ROOT_GOAL_TASK_ID: root_goal_task_id,
            }
            return {
                "context_type": "workspace_worker_runtime",
                "workspace_binding": workspace_binding,
                "workspace_id": workspace_id,
                ROOT_GOAL_TASK_ID: root_goal_task_id,
                "task_authority": "workspace",
            }
    return None


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
        user_id: str,
        event_publisher: (Callable[[str, str, dict[str, Any]], Awaitable[None]] | None) = None,
        chain_depth: int = 0,
    ) -> None:
        """Schedule mention routing as a background task (non-blocking)."""
        task = asyncio.create_task(
            self.route_mentions(
                workspace_id=workspace_id,
                message=message,
                tenant_id=tenant_id,
                project_id=project_id,
                user_id=user_id,
                event_publisher=event_publisher,
                chain_depth=chain_depth,
            )
        )
        _background_tasks.add(task)

        def _finalize(background_task: asyncio.Task[Any]) -> None:
            _background_tasks.discard(background_task)
            try:
                exc = background_task.exception()
            except asyncio.CancelledError:
                return
            if exc is not None:
                logger.exception(
                    "Workspace mention background routing task failed",
                    exc_info=exc,
                    extra={
                        "workspace_id": workspace_id,
                        "project_id": project_id,
                        "tenant_id": tenant_id,
                        "message_id": getattr(message, "id", None),
                    },
                )

        task.add_done_callback(_finalize)

    async def route_mentions(
        self,
        workspace_id: str,
        message: WorkspaceMessage,
        tenant_id: str,
        project_id: str,
        user_id: str,
        event_publisher: (Callable[[str, str, dict[str, Any]], Awaitable[None]] | None) = None,
        chain_depth: int = 0,
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
                    user_id=user_id,
                    event_publisher=event_publisher,
                    chain_depth=chain_depth,
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
                    user_id=user_id,
                    event_publisher=event_publisher,
                )

    async def _trigger_agent(
        self,
        workspace_id: str,
        agent: WorkspaceAgent,
        message: WorkspaceMessage,
        tenant_id: str,
        project_id: str,
        user_id: str,
        event_publisher: (Callable[[str, str, dict[str, Any]], Awaitable[None]] | None) = None,
        chain_depth: int = 0,
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
        conversation_scope_raw = message.metadata.get("conversation_scope")
        conversation_scope = (
            conversation_scope_raw.strip()
            if isinstance(conversation_scope_raw, str) and conversation_scope_raw.strip()
            else None
        )
        app_model_context = await _resolve_workspace_authority_context(
            self._db_session_factory,
            workspace_id=workspace_id,
            conversation_scope=conversation_scope,
        )
        autonomy_trigger = message.metadata.get("autonomy_trigger")
        if (
            app_model_context is not None
            and isinstance(autonomy_trigger, dict)
            and autonomy_trigger.get(REMEDIATION_STATUS)
            in {"replan_required", "ready_for_completion"}
        ):
            app_model_context = {
                **app_model_context,
                WORKSPACE_SESSION_ROLE_KEY: WORKSPACE_ROLE_LEADER,
                WORKSPACE_TURN_TYPE_KEY: WORKSPACE_TURN_TYPE_LEADER_REPLAN,
                WORKSPACE_TOOL_MODE_KEY: WORKSPACE_TOOL_MODE_TASK_LEDGER_ONLY,
            }

        conversation_id = self.workspace_conversation_id(
            workspace_id,
            agent.agent_id,
            conversation_scope=conversation_scope,
        )

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
                    user_id=user_id,
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
            accumulated_text = ""
            has_error = False

            async for event in agent_service.stream_chat_v2(
                conversation_id=conversation_id,
                user_message=user_prompt,
                project_id=project_id,
                user_id=user_id,
                tenant_id=tenant_id,
                agent_id=agent.agent_id,
                app_model_context=app_model_context,
            ):
                event_type = event.get("type")
                logger.debug(
                    "Mention router received event type=%s for agent %s",
                    event_type,
                    agent.agent_id,
                )
                if event_type == "text_delta":
                    accumulated_text += event.get("data", {}).get("text", "")
                elif event_type == "complete":
                    final_content = event.get("data", {}).get("content", "")
                    if not final_content and accumulated_text:
                        final_content = accumulated_text
                    logger.info(
                        "Agent %s produced response (%d chars)",
                        agent_name,
                        len(final_content),
                    )
                    break
                elif event_type == "error":
                    has_error = True
                    final_content = event.get("data", {}).get(
                        "message", "An error occurred while processing your request."
                    )
                    logger.warning(
                        "Agent %s returned error: %s",
                        agent_name,
                        final_content[:200],
                    )
                    break

        logger.info(
            "Agent %s stream done: has_error=%s, final_content_len=%d",
            agent_name,
            has_error,
            len(final_content),
        )

        if has_error:
            await self._post_error_message(
                workspace_id=workspace_id,
                agent=agent,
                original_message=message,
                user_id=user_id,
                error_detail=final_content,
                event_publisher=event_publisher,
            )
            return

        if final_content:
            logger.info("Posting agent response for %s to workspace %s", agent_name, workspace_id)
            await self._post_agent_response(
                workspace_id=workspace_id,
                agent=agent,
                content=final_content,
                user_id=user_id,
                parent_message_id=message.id,
                event_publisher=event_publisher,
                chain_depth=chain_depth,
            )

    async def _post_agent_response(
        self,
        workspace_id: str,
        agent: WorkspaceAgent,
        content: str,
        user_id: str,
        parent_message_id: str | None = None,
        event_publisher: (Callable[[str, str, dict[str, Any]], Awaitable[None]] | None) = None,
        chain_depth: int = 0,
    ) -> None:
        """Post an agent's response as a workspace chat message."""
        agent_name = agent.display_name or agent.agent_id

        async with self._db_session_factory() as db:
            message_service = self._message_service_factory(db, event_publisher)
            agent_message = await message_service.send_message(
                workspace_id=workspace_id,
                sender_id=agent.agent_id,
                sender_type=MessageSenderType.AGENT,
                sender_name=agent_name,
                content=content,
                parent_message_id=parent_message_id,
            )
            await db.commit()

        # Trigger agent-to-agent mention routing if within depth limit
        if agent_message.mentions and chain_depth < _MAX_MENTION_CHAIN_DEPTH:
            await self._route_agent_mentions(
                workspace_id=workspace_id,
                message=agent_message,
                chain_depth=chain_depth + 1,
                user_id=user_id,
                event_publisher=event_publisher,
            )

    async def _post_error_message(
        self,
        workspace_id: str,
        agent: WorkspaceAgent,
        original_message: WorkspaceMessage,
        user_id: str,
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
            user_id=user_id,
            parent_message_id=original_message.id,
            event_publisher=event_publisher,
        )

    async def _route_agent_mentions(
        self,
        workspace_id: str,
        message: WorkspaceMessage,
        chain_depth: int,
        user_id: str,
        event_publisher: (Callable[[str, str, dict[str, Any]], Awaitable[None]] | None) = None,
    ) -> None:
        for mentioned_user_id in message.mentions:
            async with self._db_session_factory() as db:
                agent_repo = self._agent_repo_factory(db)
                agents = await agent_repo.find_by_workspace(workspace_id, active_only=True)
                agent_by_id: dict[str, WorkspaceAgent] = {a.agent_id: a for a in agents}
                target_agent = agent_by_id.get(mentioned_user_id)

                if target_agent:
                    try:
                        await self._handle_single_mention(
                            workspace_id=workspace_id,
                            agent=target_agent,
                            message=message,
                            user_id=user_id,
                            event_publisher=event_publisher,
                            chain_depth=chain_depth,
                        )
                    except Exception:
                        logger.exception(
                            "Failed to route mention to agent %s for agent response in workspace %s",
                            target_agent.agent_id,
                            workspace_id,
                        )

    async def _handle_single_mention(
        self,
        workspace_id: str,
        agent: WorkspaceAgent,
        message: WorkspaceMessage,
        user_id: str,
        event_publisher: (Callable[[str, str, dict[str, Any]], Awaitable[None]] | None) = None,
        chain_depth: int = 0,
    ) -> None:
        async with self._db_session_factory() as db:
            workspace_repo = self._conversation_repo_factory(db)
            workspace = await workspace_repo.find_by_id(workspace_id)

            if workspace:
                tenant_id = getattr(workspace, "tenant_id", "")
                project_id = getattr(workspace, "project_id", "")
                if not tenant_id or not project_id:
                    logger.warning(
                        "Cannot determine tenant/project for workspace %s",
                        workspace_id,
                    )
                    return
            else:
                logger.warning("Workspace %s not found", workspace_id)
                return

        await self._trigger_agent(
            workspace_id=workspace_id,
            agent=agent,
            message=message,
            tenant_id=tenant_id,
            project_id=project_id,
            user_id=user_id,
            event_publisher=event_publisher,
            chain_depth=chain_depth,
        )

    @staticmethod
    def workspace_conversation_id(
        workspace_id: str,
        agent_id: str,
        conversation_scope: str | None = None,
    ) -> str:
        """Generate a deterministic conversation ID for workspace+agent pair."""
        scope_suffix = f":scope:{conversation_scope}" if conversation_scope else ""
        return str(
            uuid.uuid5(
                uuid.NAMESPACE_DNS,
                f"workspace:{workspace_id}:agent:{agent_id}{scope_suffix}",
            )
        )
