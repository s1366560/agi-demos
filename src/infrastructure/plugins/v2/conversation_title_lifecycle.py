"""Generation-owned producer lifecycle for automatic conversation titles."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any, cast
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.events.agent_events import AgentTitleGeneratedEvent

from .agent_events import AGENT_AFTER_TURN_COMPLETE_EVENT_V2
from .artifact_content_gc_runtime import AsyncSessionFactoryServiceV2
from .boundary import (
    OPERATION_DB_SESSION_SERVICE_V2,
    OPERATION_IDENTITY_SERVICE_V2,
    OPERATION_METADATA_SERVICE_V2,
    bind_operation_context_v2,
    current_operation_context_v2,
)
from .conversation_generation_services import (
    ConversationGenerationResolverProtocolV2,
    ConversationGenerationServiceV2,
)
from .runtime import (
    ContextV2,
    OperationContextV2,
    PluginDefinitionV2,
    RuntimeV2Error,
    generated_contract_digest_v2,
)

CONVERSATION_TITLE_LIFECYCLE_MODULE_V2 = "builtin://memstack/agent/conversation-title-lifecycle"
CONVERSATION_TITLE_LIFECYCLE_SESSIONS_INJECT_V2 = "sessions"
CONVERSATION_TITLE_LIFECYCLE_GENERATION_INJECT_V2 = "conversation_generation"

type WaterfallNextV2 = Callable[[object], Awaitable[object]]

logger = logging.getLogger(__name__)


async def _continue_waterfall_v2(
    next_: WaterfallNextV2,
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    result = await next_(dict(payload))
    if not isinstance(result, Mapping):
        raise RuntimeV2Error(
            "invalid_agent_lifecycle_result",
            "conversation title lifecycle received a non-object waterfall result",
        )
    return dict(result)


def _append_title_event_v2(
    payload: Mapping[str, Any],
    event: dict[str, Any],
) -> dict[str, Any]:
    updated = dict(payload)
    existing = updated.get("emitted_events")
    events = list(existing) if isinstance(existing, list) else []
    events.append(event)
    updated["emitted_events"] = events
    return updated


def _child_identity_v2(parent: OperationContextV2) -> dict[str, str]:
    raw_identity = parent.require(OPERATION_IDENTITY_SERVICE_V2)
    if not isinstance(raw_identity, Mapping):
        raise RuntimeV2Error(
            "invalid_operation_identity",
            "conversation title lifecycle requires parent operation identity",
        )
    identity = cast(Mapping[str, object], raw_identity)
    scope = parent.context.scope
    tenant_id = scope.tenant_id
    project_id = scope.project_id
    user_id = identity.get("user_id")
    supplied_tenant_id = identity.get("tenant_id")
    supplied_project_id = identity.get("project_id")
    if not all(isinstance(value, str) and value for value in (tenant_id, project_id, user_id)):
        raise RuntimeV2Error(
            "invalid_operation_identity",
            "conversation title lifecycle requires tenant, project, and user identity",
        )
    if supplied_tenant_id is not None and supplied_tenant_id != tenant_id:
        raise RuntimeV2Error(
            "operation_identity_scope_mismatch",
            "conversation title lifecycle tenant identity does not match its scope",
        )
    if supplied_project_id is not None and supplied_project_id != project_id:
        raise RuntimeV2Error(
            "operation_identity_scope_mismatch",
            "conversation title lifecycle project identity does not match its scope",
        )
    return {
        "tenant_id": cast(str, tenant_id),
        "project_id": cast(str, project_id),
        "user_id": cast(str, user_id),
    }


def _validate_parent_payload_v2(
    parent: OperationContextV2,
    payload: Mapping[str, Any],
) -> str:
    conversation_id = payload.get("conversation_id")
    if not isinstance(conversation_id, str) or not conversation_id:
        raise RuntimeV2Error(
            "invalid_conversation_title_lifecycle_payload",
            "conversation title lifecycle requires a conversation ID",
        )
    if conversation_id != parent.context.scope.session_id:
        raise RuntimeV2Error(
            "agent_event_scope_mismatch",
            "conversation title lifecycle conversation differs from its pinned session",
        )
    operation_id = payload.get("operation_id")
    if operation_id is not None and operation_id != parent.operation_id:
        raise RuntimeV2Error(
            "agent_event_scope_mismatch",
            "conversation title lifecycle operation differs from its pinned operation",
        )
    generation_digest = payload.get("generation_digest")
    if generation_digest is not None and generation_digest != parent.descriptor.digest:
        raise RuntimeV2Error(
            "generation_descriptor_mismatch",
            "conversation title lifecycle generation differs from its pinned operation",
        )
    return conversation_id


async def _rollback_v2(db: AsyncSession) -> None:
    try:
        await db.rollback()
    except Exception:
        logger.debug("Conversation title lifecycle rollback failed", exc_info=True)


@dataclass(frozen=True, kw_only=True)
class ConversationTitleLifecycleV2:
    """Generate an initial title inside the exact admitted turn generation."""

    sessions: AsyncSessionFactoryServiceV2
    conversation_generation: ConversationGenerationResolverProtocolV2

    async def handle(
        self,
        payload: Mapping[str, Any],
        next_: WaterfallNextV2,
    ) -> dict[str, Any]:
        if payload.get("success") is not True:
            return await _continue_waterfall_v2(next_, payload)

        title_event: dict[str, Any] | None = None

        try:
            parent = current_operation_context_v2()
            conversation_id = _validate_parent_payload_v2(parent, payload)
            identity = _child_identity_v2(parent)
            child_operation_id = f"{parent.operation_id}:conversation-title:{uuid4().hex}"
            async with self.sessions.factory() as db:
                try:
                    child = OperationContextV2(
                        generation=parent.generation,
                        operation_id=child_operation_id,
                        scope=parent.context.scope,
                    )
                    async with child:
                        _ = child.provide(OPERATION_DB_SESSION_SERVICE_V2, db)
                        _ = child.provide(OPERATION_IDENTITY_SERVICE_V2, identity)
                        _ = child.provide(
                            OPERATION_METADATA_SERVICE_V2,
                            {
                                "kind": "conversation-title-lifecycle",
                                "parent_operation_id": parent.operation_id,
                            },
                        )
                        with bind_operation_context_v2(child):
                            service = self.conversation_generation.resolve(child)
                            if not isinstance(service, ConversationGenerationServiceV2):
                                raise RuntimeV2Error(
                                    "invalid_conversation_generation_service",
                                    "conversation title lifecycle resolved an invalid service",
                                )
                            updated = await service.generate_initial_title(
                                conversation_id=conversation_id,
                            )
                            if updated is None:
                                await db.rollback()
                            else:
                                await db.commit()
                                try:
                                    await service.after_update_committed()
                                except Exception:
                                    logger.warning(
                                        "Conversation title cache invalidation failed after commit",
                                        exc_info=True,
                                    )

                    if updated is not None:
                        event = AgentTitleGeneratedEvent(
                            conversation_id=conversation_id,
                            title=updated.title,
                        ).to_event_dict()
                        event_data = dict(event["data"])
                        event_data.update(
                            {
                                "plugin_generation": parent.descriptor.to_payload(),
                                "operation_id": child_operation_id,
                                "parent_operation_id": parent.operation_id,
                            }
                        )
                        event["data"] = event_data
                        title_event = dict(event)
                except asyncio.CancelledError:
                    await _rollback_v2(db)
                    raise
                except Exception:
                    await _rollback_v2(db)
                    raise
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning(
                "Conversation title lifecycle failed without fallback",
                extra={
                    "error_type": type(exc).__name__,
                    "has_conversation_id": bool(payload.get("conversation_id")),
                    "has_operation_id": bool(payload.get("operation_id")),
                },
            )
            return await _continue_waterfall_v2(next_, payload)

        next_payload = (
            payload if title_event is None else _append_title_event_v2(payload, title_event)
        )
        return await _continue_waterfall_v2(next_, next_payload)


def _apply_conversation_title_lifecycle_v2(
    context: ContextV2,
    config: Mapping[str, Any],
) -> None:
    if config:
        raise ValueError("conversation title lifecycle module does not accept config")
    sessions = context.require(CONVERSATION_TITLE_LIFECYCLE_SESSIONS_INJECT_V2)
    if not isinstance(sessions, AsyncSessionFactoryServiceV2):
        raise RuntimeV2Error(
            "invalid_conversation_title_session_factory",
            "conversation title lifecycle requires the async session factory Provider",
        )
    conversation_generation = context.require(CONVERSATION_TITLE_LIFECYCLE_GENERATION_INJECT_V2)
    if not isinstance(conversation_generation, ConversationGenerationResolverProtocolV2):
        raise RuntimeV2Error(
            "invalid_conversation_title_generation_provider",
            "conversation title lifecycle requires the conversation generation Provider",
        )
    lifecycle = ConversationTitleLifecycleV2(
        sessions=sessions,
        conversation_generation=conversation_generation,
    )
    _ = context.on(AGENT_AFTER_TURN_COMPLETE_EVENT_V2, lifecycle.handle)


def conversation_title_lifecycle_definition_v2() -> PluginDefinitionV2:
    return PluginDefinitionV2(
        module_ref=CONVERSATION_TITLE_LIFECYCLE_MODULE_V2,
        contract_digest=generated_contract_digest_v2(CONVERSATION_TITLE_LIFECYCLE_MODULE_V2),
        apply=_apply_conversation_title_lifecycle_v2,
    )


__all__ = [
    "CONVERSATION_TITLE_LIFECYCLE_GENERATION_INJECT_V2",
    "CONVERSATION_TITLE_LIFECYCLE_MODULE_V2",
    "CONVERSATION_TITLE_LIFECYCLE_SESSIONS_INJECT_V2",
    "ConversationTitleLifecycleV2",
    "conversation_title_lifecycle_definition_v2",
]
