"""Workspace LLM session persistence helpers."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from src.domain.model.agent import (
    Conversation,
    ConversationStatus,
)
from src.infrastructure.plugins.v2.artifact_content_gc_runtime import (
    ASYNC_SESSION_FACTORY_SERVICE_V2,
    AsyncSessionFactoryServiceV2,
)
from src.infrastructure.plugins.v2.boundary import (
    OPERATION_DB_SESSION_SERVICE_V2,
    OPERATION_IDENTITY_SERVICE_V2,
    OPERATION_METADATA_SERVICE_V2,
    pin_agent_turn_operation_v2,
)
from src.infrastructure.plugins.v2.conversation_access_services import (
    CONVERSATION_ACCESS_SERVICE_V2,
    ConversationAccessResolverProtocolV2,
)
from src.infrastructure.plugins.v2.runtime import RuntimeV2Error

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
    resolved_user_id = actor_user_id.strip() if isinstance(actor_user_id, str) else ""
    if not resolved_user_id:
        logger.warning(
            "workspace_llm_session.actor_user_missing",
            extra={"workspace_id": workspace_id, "conversation_id": conversation_id},
        )
        return False

    try:
        async with pin_agent_turn_operation_v2(
            operation_id=f"workspace-llm-session:{uuid.uuid4()}",
            tenant_id=tenant_id,
            project_id=project_id,
            session_id=conversation_id,
            services={
                OPERATION_IDENTITY_SERVICE_V2: {
                    "tenant_id": tenant_id,
                    "project_id": project_id,
                    "user_id": resolved_user_id,
                },
                OPERATION_METADATA_SERVICE_V2: {
                    "kind": "workspace-llm-session",
                    "conversation_id": conversation_id,
                    "workspace_id": workspace_id,
                    "agent_id": agent_id,
                    "stage": stage,
                },
            },
            force_process_host_lease=True,
        ) as operation:
            sessions = operation.require(ASYNC_SESSION_FACTORY_SERVICE_V2)
            if not isinstance(sessions, AsyncSessionFactoryServiceV2):
                raise RuntimeV2Error(
                    "invalid_workspace_session_factory",
                    "Workspace LLM session factory Provider is invalid",
                )
            resolver = operation.require(CONVERSATION_ACCESS_SERVICE_V2)
            if not isinstance(resolver, ConversationAccessResolverProtocolV2):
                raise RuntimeV2Error(
                    "invalid_workspace_conversation_access",
                    "Workspace LLM conversation access Provider is invalid",
                )

            async with sessions.factory() as db:
                _ = operation.provide(
                    OPERATION_DB_SESSION_SERVICE_V2,
                    db,
                    label="workspace-llm-session-db",
                )
                service = resolver.resolve(operation)
                created_at = datetime.now(UTC)
                existing = await service.find_by_id(conversation_id)
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
                        project_id=project_id,
                        tenant_id=tenant_id,
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
                    saved = await service.save_scoped_conversation(
                        conversation=conversation,
                        project_id=project_id,
                        tenant_id=tenant_id,
                        user_id=resolved_user_id,
                    )
                    if saved is None:
                        return False
                else:
                    if (
                        existing.project_id != project_id
                        or existing.tenant_id != tenant_id
                        or existing.user_id != resolved_user_id
                    ):
                        logger.warning(
                            "workspace_llm_session.scope_mismatch",
                            extra={
                                "workspace_id": workspace_id,
                                "conversation_id": conversation_id,
                            },
                        )
                        return False

                    if _update_existing_workspace_conversation(
                        existing,
                        workspace_id=workspace_id,
                        linked_workspace_task_id=linked_workspace_task_id,
                        agent_id=agent_id,
                        metadata=merged_metadata,
                        updated_at=created_at,
                    ):
                        saved = await service.save_scoped_conversation(
                            conversation=existing,
                            project_id=project_id,
                            tenant_id=tenant_id,
                            user_id=resolved_user_id,
                        )
                        if saved is None:
                            return False

                await db.commit()
                await service.cache.invalidate(project_id)
                return True
    except RuntimeV2Error:
        raise
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


def _update_existing_workspace_conversation(
    conversation: Conversation,
    *,
    workspace_id: str,
    linked_workspace_task_id: str | None,
    agent_id: str,
    metadata: Mapping[str, Any],
    updated_at: datetime,
) -> bool:
    """Apply exact Workspace linkage changes before one scoped V2 save."""
    changed = False
    if conversation.workspace_id != workspace_id:
        conversation.workspace_id = workspace_id
        changed = True
    if linked_workspace_task_id and (
        conversation.linked_workspace_task_id != linked_workspace_task_id
    ):
        conversation.linked_workspace_task_id = linked_workspace_task_id
        changed = True
    agent_config = dict(conversation.agent_config or {})
    if agent_config.get("selected_agent_id") != agent_id:
        agent_config["selected_agent_id"] = agent_id
        conversation.agent_config = agent_config
        changed = True
    current_metadata = dict(conversation.metadata or {})
    next_metadata = {**current_metadata, **metadata}
    if next_metadata != current_metadata:
        conversation.metadata = next_metadata
        changed = True
    if changed:
        conversation.updated_at = updated_at
    return changed


__all__ = ["ensure_workspace_llm_conversation"]
