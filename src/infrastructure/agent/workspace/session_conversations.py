"""Workspace LLM session persistence helpers."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from src.domain.model.agent import (
    Conversation,
    ConversationStatus,
)
from src.infrastructure.adapters.secondary.persistence.database import async_session_factory
from src.infrastructure.adapters.secondary.persistence.sql_conversation_repository import (
    SqlConversationRepository,
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
            await _invalidate_conversation_list_cache(workspace.project_id or project_id)
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


async def _invalidate_conversation_list_cache(project_id: str) -> None:
    """Keep background workspace sessions visible in cached conversation lists."""
    try:
        from src.infrastructure.agent.state.agent_worker_state import get_redis_client

        redis_client = await get_redis_client()
        for prefix in ("conv_list:", "conv_count:"):
            keys = await redis_client.keys(f"{prefix}{project_id}:*")
            if keys:
                await redis_client.delete(*keys)
    except Exception:
        logger.debug(
            "workspace_llm_session.cache_invalidation_failed",
            extra={"project_id": project_id},
            exc_info=True,
        )


__all__ = ["ensure_workspace_llm_conversation"]
