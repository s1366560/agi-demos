"""Workspace LLM session persistence helpers."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, Protocol, cast, runtime_checkable

from src.domain.model.agent import (
    Conversation,
    ConversationStatus,
)
from src.infrastructure.plugins.v2.boundary import (
    OPERATION_DB_SESSION_SERVICE_V2,
    OPERATION_IDENTITY_SERVICE_V2,
)
from src.infrastructure.plugins.v2.conversation_access_services import (
    CONVERSATION_ACCESS_SERVICE_V2,
    ConversationAccessResolverProtocolV2,
    ConversationAccessServiceV2,
)
from src.infrastructure.plugins.v2.runtime import OperationContextV2, RuntimeV2Error

logger = logging.getLogger(__name__)


@runtime_checkable
class _WorkspaceConversationSessionProtocolV2(Protocol):
    async def commit(self) -> None: ...


async def ensure_workspace_llm_conversation(
    *,
    conversation_id: str,
    tenant_id: str,
    project_id: str,
    workspace_id: str,
    agent_id: str,
    title: str,
    stage: str,
    actor_user_id: str | None,
    operation: OperationContextV2,
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
        db, service = _workspace_conversation_services_v2(
            operation,
            tenant_id=tenant_id,
            project_id=project_id,
            conversation_id=conversation_id,
            actor_user_id=resolved_user_id,
        )
        return await _persist_workspace_conversation_v2(
            db=db,
            service=service,
            conversation_id=conversation_id,
            tenant_id=tenant_id,
            project_id=project_id,
            workspace_id=workspace_id,
            agent_id=agent_id,
            title=title,
            stage=stage,
            actor_user_id=resolved_user_id,
            linked_workspace_task_id=linked_workspace_task_id,
            metadata=metadata,
        )
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


def _workspace_conversation_services_v2(
    operation: OperationContextV2,
    *,
    tenant_id: str,
    project_id: str,
    conversation_id: str,
    actor_user_id: str,
) -> tuple[_WorkspaceConversationSessionProtocolV2, ConversationAccessServiceV2]:
    scope = operation.context.scope
    if (
        scope.tenant_id != tenant_id
        or scope.project_id != project_id
        or scope.session_id != conversation_id
    ):
        raise RuntimeV2Error(
            "workspace_session_operation_scope_mismatch",
            "Workspace LLM session scope differs from its pinned operation",
        )
    identity = operation.require(OPERATION_IDENTITY_SERVICE_V2)
    if not isinstance(identity, Mapping):
        raise RuntimeV2Error(
            "workspace_session_operation_identity_mismatch",
            "Workspace LLM session actor differs from its pinned operation",
        )
    identity_map = cast("Mapping[str, object]", identity)
    if identity_map.get("user_id") != actor_user_id:
        raise RuntimeV2Error(
            "workspace_session_operation_identity_mismatch",
            "Workspace LLM session actor differs from its pinned operation",
        )
    db = operation.require(OPERATION_DB_SESSION_SERVICE_V2)
    if not isinstance(db, _WorkspaceConversationSessionProtocolV2):
        raise RuntimeV2Error(
            "invalid_workspace_session_db",
            "Workspace LLM session requires a commit-capable operation DB session",
        )
    resolver = operation.require(CONVERSATION_ACCESS_SERVICE_V2)
    if not isinstance(resolver, ConversationAccessResolverProtocolV2):
        raise RuntimeV2Error(
            "invalid_workspace_conversation_access",
            "Workspace LLM conversation access Provider is invalid",
        )
    return db, resolver.resolve(operation)


async def _persist_workspace_conversation_v2(
    *,
    db: _WorkspaceConversationSessionProtocolV2,
    service: ConversationAccessServiceV2,
    conversation_id: str,
    tenant_id: str,
    project_id: str,
    workspace_id: str,
    agent_id: str,
    title: str,
    stage: str,
    actor_user_id: str,
    linked_workspace_task_id: str | None,
    metadata: Mapping[str, Any] | None,
) -> bool:
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
            user_id=actor_user_id,
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
            user_id=actor_user_id,
        )
        if saved is None:
            return False
    else:
        if (
            existing.project_id != project_id
            or existing.tenant_id != tenant_id
            or existing.user_id != actor_user_id
        ):
            logger.warning(
                "workspace_llm_session.scope_mismatch",
                extra={"workspace_id": workspace_id, "conversation_id": conversation_id},
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
                user_id=actor_user_id,
            )
            if saved is None:
                return False

    await db.commit()
    await service.cache.invalidate(project_id)
    return True


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
