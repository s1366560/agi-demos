"""Workspace LLM session persistence helpers."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.agent import (
    Conversation,
    ConversationStatus,
    Message,
    MessageRole,
    MessageType,
)
from src.infrastructure.adapters.secondary.persistence.database import async_session_factory
from src.infrastructure.adapters.secondary.persistence.models import (
    AgentExecutionEvent as DBAgentExecutionEvent,
)
from src.infrastructure.adapters.secondary.persistence.sql_conversation_repository import (
    SqlConversationRepository,
)
from src.infrastructure.adapters.secondary.persistence.sql_message_repository import (
    SqlMessageRepository,
)
from src.infrastructure.adapters.secondary.persistence.sql_workspace_repository import (
    SqlWorkspaceRepository,
)

logger = logging.getLogger(__name__)


async def ensure_workspace_llm_conversation(
    *,
    conversation_id: str,
    tenant_id: str,
    project_id: str,
    workspace_id: str,
    agent_id: str,
    title: str,
    stage: str,
    actor_user_id: str | None = None,
    linked_workspace_task_id: str | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> bool:
    """Persist a workspace-scoped Conversation row for an LLM-backed runtime turn."""
    try:
        async with async_session_factory() as db:
            workspace = await SqlWorkspaceRepository(db).find_by_id(workspace_id)
            if workspace is None:
                logger.warning(
                    "workspace_llm_session.workspace_not_found",
                    extra={"workspace_id": workspace_id, "conversation_id": conversation_id},
                )
                return False

            created_at = datetime.now(UTC)
            repo = SqlConversationRepository(db)
            existing = await repo.find_by_id(conversation_id)
            resolved_user_id = actor_user_id or workspace.created_by
            merged_metadata: dict[str, Any] = {
                "workspace_id": workspace_id,
                "agent_id": agent_id,
                "workspace_llm_stage": stage,
                "source": "workspace_llm_session",
                "created_at": created_at.isoformat(),
                **dict(metadata or {}),
            }

            if existing is None:
                conversation = Conversation(
                    id=conversation_id,
                    project_id=workspace.project_id or project_id,
                    tenant_id=workspace.tenant_id or tenant_id,
                    user_id=resolved_user_id,
                    title=title,
                    status=ConversationStatus.ACTIVE,
                    agent_config={"selected_agent_id": agent_id},
                    metadata=merged_metadata,
                    message_count=0,
                    created_at=created_at,
                    workspace_id=workspace_id,
                    linked_workspace_task_id=linked_workspace_task_id,
                )
                _ = await repo.save(conversation)
            else:
                changed = False
                if existing.workspace_id != workspace_id:
                    existing.workspace_id = workspace_id
                    changed = True
                if linked_workspace_task_id and (
                    existing.linked_workspace_task_id != linked_workspace_task_id
                ):
                    existing.linked_workspace_task_id = linked_workspace_task_id
                    changed = True
                agent_config = dict(existing.agent_config or {})
                if agent_config.get("selected_agent_id") != agent_id:
                    agent_config["selected_agent_id"] = agent_id
                    existing.agent_config = agent_config
                    changed = True
                current_metadata = dict(existing.metadata or {})
                next_metadata = {**current_metadata, **merged_metadata}
                if next_metadata != current_metadata:
                    existing.metadata = next_metadata
                    changed = True
                if changed:
                    existing.updated_at = created_at
                    _ = await repo.save(existing)

            await db.commit()
            return True
    except Exception:
        logger.warning(
            "workspace_llm_session.persist_failed",
            extra={
                "workspace_id": workspace_id,
                "conversation_id": conversation_id,
                "stage": stage,
            },
            exc_info=True,
        )
        return False


async def append_workspace_llm_turn_messages(
    *,
    conversation_id: str,
    user_prompt: str,
    assistant_content: str,
    agent_id: str,
    stage: str,
    metadata: Mapping[str, Any] | None = None,
) -> bool:
    """Append visible user/assistant messages for an internal workspace LLM turn."""
    try:
        async with async_session_factory() as db:
            conversation_repo = SqlConversationRepository(db)
            conversation = await conversation_repo.find_by_id(conversation_id)
            if conversation is None:
                logger.warning(
                    "workspace_llm_session.messages_conversation_not_found",
                    extra={"conversation_id": conversation_id, "stage": stage},
                )
                return False

            now = datetime.now(UTC)
            turn_metadata = {
                "workspace_llm_stage": stage,
                "source": "workspace_llm_session",
                **dict(metadata or {}),
            }
            message_repo = SqlMessageRepository(db)
            user_message_id = f"{conversation_id}:user"
            assistant_message_id = f"{conversation_id}:assistant"
            await message_repo.save(
                Message(
                    id=user_message_id,
                    conversation_id=conversation_id,
                    role=MessageRole.USER,
                    content=user_prompt,
                    message_type=MessageType.TEXT,
                    metadata={**turn_metadata, "workspace_llm_message_role": "input"},
                    created_at=now,
                )
            )
            await message_repo.save(
                Message(
                    id=assistant_message_id,
                    conversation_id=conversation_id,
                    role=MessageRole.ASSISTANT,
                    content=assistant_content or "(no verifier response content captured)",
                    message_type=MessageType.TEXT,
                    metadata={**turn_metadata, "workspace_llm_message_role": "output"},
                    created_at=now,
                    sender_agent_id=agent_id,
                )
            )
            await _append_workspace_llm_timeline_events(
                db,
                conversation_id=conversation_id,
                user_message_id=user_message_id,
                assistant_message_id=assistant_message_id,
                user_prompt=user_prompt,
                assistant_content=assistant_content
                or "(no verifier response content captured)",
                agent_id=agent_id,
                stage=stage,
                metadata=turn_metadata,
                created_at=now,
            )
            conversation.message_count = await message_repo.count_by_conversation(
                conversation_id
            )
            conversation.updated_at = now
            await conversation_repo.save(conversation)
            await db.commit()
            return True
    except Exception:
        logger.warning(
            "workspace_llm_session.messages_persist_failed",
            extra={"conversation_id": conversation_id, "stage": stage},
            exc_info=True,
        )
        return False


async def _append_workspace_llm_timeline_events(
    db: AsyncSession,
    *,
    conversation_id: str,
    user_message_id: str,
    assistant_message_id: str,
    user_prompt: str,
    assistant_content: str,
    agent_id: str,
    stage: str,
    metadata: Mapping[str, Any],
    created_at: datetime,
) -> None:
    event_time_us = int(created_at.timestamp() * 1_000_000)
    correlation_id = uuid.uuid5(uuid.NAMESPACE_URL, conversation_id).hex[
        :100
    ]
    values = [
        {
            "id": f"{user_message_id}:event",
            "conversation_id": conversation_id,
            "message_id": user_message_id,
            "event_type": "user_message",
            "event_data": {
                "message_id": user_message_id,
                "content": _event_text(user_prompt),
                "role": "user",
                "workspace_llm_stage": stage,
                "metadata": dict(metadata),
            },
            "event_time_us": event_time_us,
            "event_counter": 0,
            "correlation_id": correlation_id,
            "created_at": created_at,
        },
        {
            "id": f"{assistant_message_id}:event",
            "conversation_id": conversation_id,
            "message_id": assistant_message_id,
            "event_type": "assistant_message",
            "event_data": {
                "message_id": assistant_message_id,
                "content": _event_text(assistant_content),
                "role": "assistant",
                "source": "workspace_llm_session",
                "agent_id": agent_id,
                "workspace_llm_stage": stage,
                "metadata": dict(metadata),
            },
            "event_time_us": event_time_us,
            "event_counter": 1,
            "correlation_id": correlation_id,
            "created_at": created_at,
        },
    ]
    stmt = (
        insert(DBAgentExecutionEvent)
        .values(values)
        .on_conflict_do_nothing(index_elements=["id"])
    )
    await db.execute(stmt)


def _event_text(value: str) -> str:
    return str(value or "").replace("\x00", "[NUL]")


__all__ = ["append_workspace_llm_turn_messages", "ensure_workspace_llm_conversation"]
