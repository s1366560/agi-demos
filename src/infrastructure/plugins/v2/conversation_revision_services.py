"""Generation-owned transaction seam for conversation fork, edit, and tool undo."""

from __future__ import annotations

import time
import uuid
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol, cast, runtime_checkable

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.plugins.runtime import PluginGenerationDescriptorV2
from src.infrastructure.adapters.secondary.common.base_repository import refresh_select_statement
from src.infrastructure.adapters.secondary.persistence.models import (
    AgentExecutionEvent,
    Conversation,
    Message,
    Project,
    ToolExecutionRecord,
    UserProject,
    UserTenant,
)
from src.infrastructure.i18n import gettext as _

from .conversation_access_services import (
    ConversationCacheClientProtocolV2,
    ConversationCacheInvalidatorProtocolV2,
    RedisConversationCacheInvalidatorV2,
)
from .redis_runtime import RedisRuntimeServiceV2
from .runtime import (
    ContextV2,
    OperationContextV2,
    PluginDefinitionV2,
    RuntimeV2Error,
    generated_contract_digest_v2,
)
from .session_event_log import (
    HITL_TOOL_RESULT_APPLIED_EVENT_V2,
    MODEL_MESSAGE_COMMITTED_EVENT_V2,
    TURN_ADMITTED_EVENT_V2,
)

CONVERSATION_REVISION_PROVIDER_MODULE_V2 = (
    "builtin://memstack/persistence/conversation-revision-provider"
)
CONVERSATION_REVISION_PROVIDER_SERVICE_V2 = "service:persistence.conversation-revision-provider"
CONVERSATION_REVISION_MODULE_V2 = "builtin://memstack/application/conversation-revision"
CONVERSATION_REVISION_SERVICE_V2 = "service:application.conversation-revision"
CONVERSATION_REVISION_PROVIDER_INJECT_V2 = "provider"
CONVERSATION_REVISION_REDIS_INJECT_V2 = "redis"

_OPERATION_DB_SESSION_SERVICE_V2 = "service:operation.db-session"

MODEL_MESSAGE_REVISED_EVENT_V2 = "model_message_revised"

_LEGACY_MODEL_EVENT_ROLES = {
    "assistant_message": "assistant",
    "user_message": "user",
}
_TYPED_MODEL_EVENT_TYPES = frozenset(
    {
        HITL_TOOL_RESULT_APPLIED_EVENT_V2,
        MODEL_MESSAGE_COMMITTED_EVENT_V2,
        TURN_ADMITTED_EVENT_V2,
    }
)
_MODEL_EVENT_TYPES = frozenset({*_LEGACY_MODEL_EVENT_ROLES, *_TYPED_MODEL_EVENT_TYPES})
_MESSAGE_COUNT_EVENT_TYPES = frozenset(
    {
        "assistant_message",
        TURN_ADMITTED_EVENT_V2,
        "user_message",
    }
)


class ConversationRevisionErrorV2(RuntimeError):
    """Base error for exact, scoped revision failures."""


class ConversationRevisionConversationNotFoundV2(ConversationRevisionErrorV2):
    """The requested conversation is absent from the caller's tenant."""


class ConversationRevisionAccessDeniedV2(ConversationRevisionErrorV2):
    """The caller does not own or cannot access the conversation project."""


class ConversationRevisionMessageNotFoundV2(ConversationRevisionErrorV2):
    """The branch or edited message is absent from the authoritative event log."""


class ConversationRevisionToolExecutionNotFoundV2(ConversationRevisionErrorV2):
    """The requested tool execution is absent from the scoped conversation."""


@dataclass(frozen=True, kw_only=True)
class ForkedConversationV2:
    conversation_id: str
    title: str
    parent_conversation_id: str
    project_id: str

    def to_dict(self) -> dict[str, str]:
        return {
            "id": self.conversation_id,
            "title": self.title,
            "parent_id": self.parent_conversation_id,
        }


@dataclass(frozen=True, kw_only=True)
class EditedConversationMessageV2:
    message_id: str
    content: str
    original_content: str
    version: int
    edited_at: datetime
    project_id: str

    def to_dict(self) -> dict[str, str | int]:
        return {
            "id": self.message_id,
            "content": self.content,
            "version": self.version,
            "edited_at": str(self.edited_at),
        }


@dataclass(frozen=True, kw_only=True)
class ToolUndoRequestV2:
    message_id: str
    tool_name: str
    project_id: str

    def to_dict(self) -> dict[str, str]:
        return {
            "status": "undo_requested",
            "message_id": self.message_id,
            "tool_name": self.tool_name,
        }


@runtime_checkable
class ConversationRevisionTransactionProtocolV2(Protocol):
    async def fork_conversation(
        self,
        *,
        conversation_id: str,
        branch_message_id: str,
        tenant_id: str,
        user_id: str,
    ) -> ForkedConversationV2: ...

    async def edit_message(
        self,
        *,
        conversation_id: str,
        message_id: str,
        content: str | None,
        tenant_id: str,
        user_id: str,
    ) -> EditedConversationMessageV2: ...

    async def request_tool_undo(
        self,
        *,
        conversation_id: str,
        execution_id: str,
        tenant_id: str,
        user_id: str,
    ) -> ToolUndoRequestV2: ...


def _require_identifier(value: str, *, field_name: str) -> None:
    if not value.strip():
        raise ValueError(f"{field_name} must be non-empty")


def _positive_version(value: object) -> int:
    if isinstance(value, bool):
        return 1
    try:
        parsed = int(cast(Any, value))
    except (TypeError, ValueError):
        return 1
    return parsed if parsed > 0 else 1


def _public_message_id(event: AgentExecutionEvent) -> str | None:
    if event.event_type == TURN_ADMITTED_EVENT_V2:
        return event.message_id
    raw_message_id = (event.event_data or {}).get("message_id")
    if isinstance(raw_message_id, str) and raw_message_id.strip():
        return raw_message_id
    if event.event_type in _LEGACY_MODEL_EVENT_ROLES:
        return event.message_id
    return None


def _model_message_content(event: AgentExecutionEvent) -> tuple[str, str]:
    event_data = event.event_data or {}
    if event.event_type in _TYPED_MODEL_EVENT_TYPES:
        raw_model_message = event_data.get("model_message")
        if not isinstance(raw_model_message, Mapping):
            raise ConversationRevisionMessageNotFoundV2(event.id)
        typed_model_message = cast("Mapping[str, Any]", raw_model_message)
        role = typed_model_message.get("role")
        content = typed_model_message.get("content")
    else:
        role = event_data.get("role", _LEGACY_MODEL_EVENT_ROLES[event.event_type])
        content = event_data.get("content")
    if not isinstance(role, str) or not isinstance(content, str):
        raise ConversationRevisionMessageNotFoundV2(event.id)
    return role, content


@dataclass(frozen=True, kw_only=True)
class SqlConversationRevisionTransactionV2:
    """Use one request-owned SQL session for message state and its event-log audit."""

    db: AsyncSession
    descriptor: PluginGenerationDescriptorV2

    async def _scoped_conversation(
        self,
        *,
        conversation_id: str,
        tenant_id: str,
        user_id: str,
    ) -> Conversation:
        _require_identifier(conversation_id, field_name="conversation_id")
        _require_identifier(tenant_id, field_name="tenant_id")
        _require_identifier(user_id, field_name="user_id")
        result = await self.db.execute(
            refresh_select_statement(
                select(Conversation)
                .where(Conversation.id == conversation_id)
                .limit(1)
                .with_for_update()
            )
        )
        conversation = cast("Conversation | None", result.scalar_one_or_none())
        if conversation is None or conversation.tenant_id != tenant_id:
            raise ConversationRevisionConversationNotFoundV2(conversation_id)
        if conversation.user_id != user_id:
            raise ConversationRevisionAccessDeniedV2(conversation_id)

        access_result = await self.db.execute(
            refresh_select_statement(
                select(Project.id).where(
                    Project.id == conversation.project_id,
                    Project.tenant_id == tenant_id,
                    exists(
                        select(UserProject.id).where(
                            UserProject.user_id == user_id,
                            UserProject.project_id == conversation.project_id,
                        )
                    ),
                    exists(
                        select(UserTenant.id).where(
                            UserTenant.user_id == user_id,
                            UserTenant.tenant_id == tenant_id,
                        )
                    ),
                )
            )
        )
        if access_result.scalar_one_or_none() is None:
            raise ConversationRevisionAccessDeniedV2(conversation_id)
        return conversation

    async def _model_events(self, conversation_id: str) -> list[AgentExecutionEvent]:
        result = await self.db.execute(
            refresh_select_statement(
                select(AgentExecutionEvent)
                .where(
                    AgentExecutionEvent.conversation_id == conversation_id,
                    AgentExecutionEvent.event_type.in_(_MODEL_EVENT_TYPES),
                )
                .order_by(
                    AgentExecutionEvent.event_time_us,
                    AgentExecutionEvent.event_counter,
                )
                .with_for_update()
            )
        )
        return list(result.scalars().all())

    async def _next_cursor(self, conversation_id: str) -> tuple[int, int]:
        result = await self.db.execute(
            select(
                AgentExecutionEvent.event_time_us,
                AgentExecutionEvent.event_counter,
            )
            .where(AgentExecutionEvent.conversation_id == conversation_id)
            .order_by(
                AgentExecutionEvent.event_time_us.desc(),
                AgentExecutionEvent.event_counter.desc(),
            )
            .limit(1)
        )
        row = result.one_or_none()
        now_us = time.time_ns() // 1_000
        if row is None or now_us > int(row[0]):
            return now_us, 0
        return int(row[0]), int(row[1]) + 1

    @staticmethod
    def _find_message_event(
        events: list[AgentExecutionEvent],
        message_id: str,
    ) -> AgentExecutionEvent:
        for event in events:
            if _public_message_id(event) == message_id:
                return event
        raise ConversationRevisionMessageNotFoundV2(message_id)

    async def fork_conversation(
        self,
        *,
        conversation_id: str,
        branch_message_id: str,
        tenant_id: str,
        user_id: str,
    ) -> ForkedConversationV2:
        _require_identifier(branch_message_id, field_name="branch_message_id")
        source = await self._scoped_conversation(
            conversation_id=conversation_id,
            tenant_id=tenant_id,
            user_id=user_id,
        )
        source_events = await self._model_events(source.id)
        branch = self._find_message_event(source_events, branch_message_id)
        copied_events = [
            event
            for event in source_events
            if (event.event_time_us, event.event_counter)
            <= (branch.event_time_us, branch.event_counter)
        ]

        fork_id = str(uuid.uuid4())
        fork_title = f"{source.title[:493]} (fork)"
        now = datetime.now(UTC)
        message_count = sum(
            event.event_type in _MESSAGE_COUNT_EVENT_TYPES for event in copied_events
        )
        fork = Conversation(
            id=fork_id,
            project_id=source.project_id,
            tenant_id=source.tenant_id,
            user_id=user_id,
            title=fork_title,
            status="active",
            agent_config={},
            meta={},
            message_count=message_count,
            created_at=now,
            updated_at=now if copied_events else None,
            current_mode="build",
            parent_conversation_id=source.id,
            branch_point_message_id=branch_message_id,
            fork_source_id=source.id,
            merge_strategy="result_only",
            participant_agents=[],
        )
        self.db.add(fork)
        await self.db.flush()

        group_ids: dict[str, str] = {}
        public_ids: dict[str, str] = {}
        base_time_us = time.time_ns() // 1_000
        descriptor_payload = self.descriptor.to_payload()
        for counter, source_event in enumerate(copied_events):
            target_group_id = group_ids.setdefault(
                source_event.message_id or source_event.id,
                str(uuid.uuid4()),
            )
            event_data = deepcopy(source_event.event_data or {})
            original_public_id = event_data.get("message_id")
            if isinstance(original_public_id, str) and original_public_id.strip():
                event_data["message_id"] = public_ids.setdefault(
                    original_public_id,
                    str(uuid.uuid4()),
                )
            raw_model_message = event_data.get("model_message")
            if isinstance(raw_model_message, Mapping):
                model_message: dict[str, Any] = dict(cast("Mapping[str, Any]", raw_model_message))
                model_message_id = model_message.get("message_id")
                if isinstance(model_message_id, str) and model_message_id.strip():
                    model_message["message_id"] = public_ids.setdefault(
                        model_message_id,
                        str(uuid.uuid4()),
                    )
                event_data["model_message"] = model_message
            source_generation = event_data.get("plugin_generation")
            if source_generation is not None:
                event_data["source_plugin_generation"] = source_generation
            event_data["plugin_generation"] = descriptor_payload
            event_data["fork_source_conversation_id"] = source.id
            event_data["fork_source_event_id"] = source_event.id
            self.db.add(
                AgentExecutionEvent(
                    id=str(uuid.uuid4()),
                    conversation_id=fork_id,
                    message_id=target_group_id,
                    event_type=source_event.event_type,
                    event_data=event_data,
                    event_time_us=base_time_us,
                    event_counter=counter,
                    correlation_id=f"conversation-fork:{fork_id}",
                    created_at=now,
                )
            )
        await self.db.flush()
        return ForkedConversationV2(
            conversation_id=fork_id,
            title=fork_title,
            parent_conversation_id=source.id,
            project_id=source.project_id,
        )

    async def edit_message(
        self,
        *,
        conversation_id: str,
        message_id: str,
        content: str | None,
        tenant_id: str,
        user_id: str,
    ) -> EditedConversationMessageV2:
        _require_identifier(message_id, field_name="message_id")
        source = await self._scoped_conversation(
            conversation_id=conversation_id,
            tenant_id=tenant_id,
            user_id=user_id,
        )
        target = self._find_message_event(await self._model_events(source.id), message_id)
        role, current_content = _model_message_content(target)
        next_content = current_content if content is None else content
        event_data = deepcopy(target.event_data or {})
        original_content = event_data.get("original_content")
        if not isinstance(original_content, str):
            original_content = current_content
        version = _positive_version(event_data.get("version")) + 1
        edited_at = datetime.now(UTC)

        if target.event_type in _TYPED_MODEL_EVENT_TYPES:
            model_message = dict(cast(Mapping[str, Any], event_data["model_message"]))
            model_message["content"] = next_content
            event_data["model_message"] = model_message
        else:
            event_data["content"] = next_content
        event_data["original_content"] = original_content
        event_data["version"] = version
        event_data["edited_at"] = edited_at.isoformat()
        event_data["last_edited_plugin_generation"] = self.descriptor.to_payload()
        target.event_data = event_data

        legacy = await self.db.get(Message, message_id)
        if legacy is not None and legacy.conversation_id == source.id:
            if legacy.original_content is None:
                legacy.original_content = legacy.content
            legacy.content = next_content
            legacy.version = version
            legacy.edited_at = edited_at

        event_time_us, event_counter = await self._next_cursor(source.id)
        self.db.add(
            AgentExecutionEvent(
                id=str(uuid.uuid4()),
                conversation_id=source.id,
                message_id=target.message_id or message_id,
                event_type=MODEL_MESSAGE_REVISED_EVENT_V2,
                event_data={
                    "target_event_id": target.id,
                    "target_message_id": message_id,
                    "role": role,
                    "content": next_content,
                    "original_content": original_content,
                    "version": version,
                    "edited_at": edited_at.isoformat(),
                    "plugin_generation": self.descriptor.to_payload(),
                },
                event_time_us=event_time_us,
                event_counter=event_counter,
                correlation_id=f"conversation-edit:{message_id}",
                created_at=edited_at,
            )
        )
        source.updated_at = edited_at
        await self.db.flush()
        return EditedConversationMessageV2(
            message_id=message_id,
            content=next_content,
            original_content=original_content,
            version=version,
            edited_at=edited_at,
            project_id=source.project_id,
        )

    async def request_tool_undo(
        self,
        *,
        conversation_id: str,
        execution_id: str,
        tenant_id: str,
        user_id: str,
    ) -> ToolUndoRequestV2:
        _require_identifier(execution_id, field_name="execution_id")
        source = await self._scoped_conversation(
            conversation_id=conversation_id,
            tenant_id=tenant_id,
            user_id=user_id,
        )
        execution = await self.db.get(ToolExecutionRecord, execution_id)
        if execution is None or execution.conversation_id != source.id:
            raise ConversationRevisionToolExecutionNotFoundV2(execution_id)

        message_id = str(uuid.uuid4())
        content = _(
            "Please undo the previous tool execution: {tool_name}. Revert any changes made."
        ).format(tool_name=execution.tool_name)
        event_time_us, event_counter = await self._next_cursor(source.id)
        created_at = datetime.now(UTC)
        self.db.add(
            AgentExecutionEvent(
                id=str(uuid.uuid4()),
                conversation_id=source.id,
                message_id=message_id,
                event_type=TURN_ADMITTED_EVENT_V2,
                event_data={
                    "source": "tool_undo",
                    "tool_execution_id": execution.id,
                    "tool_name": execution.tool_name,
                    "model_message": {"role": "user", "content": content},
                    "plugin_generation": self.descriptor.to_payload(),
                },
                event_time_us=event_time_us,
                event_counter=event_counter,
                correlation_id=f"tool-undo:{execution.id}",
                created_at=created_at,
            )
        )
        source.message_count = (source.message_count or 0) + 1
        source.updated_at = created_at
        await self.db.flush()
        return ToolUndoRequestV2(
            message_id=message_id,
            tool_name=execution.tool_name,
            project_id=source.project_id,
        )


@runtime_checkable
class ConversationRevisionProviderProtocolV2(Protocol):
    def build(self, operation: OperationContextV2) -> ConversationRevisionTransactionProtocolV2: ...


@dataclass(frozen=True, kw_only=True)
class SqlConversationRevisionProviderV2:
    strategy: str

    def build(self, operation: OperationContextV2) -> ConversationRevisionTransactionProtocolV2:
        db = operation.require(_OPERATION_DB_SESSION_SERVICE_V2)
        if not isinstance(db, AsyncSession):
            raise RuntimeV2Error(
                "invalid_operation_db_session",
                "conversation revision requires an AsyncSession operation service",
            )
        return SqlConversationRevisionTransactionV2(
            db=db,
            descriptor=operation.descriptor,
        )


@dataclass(frozen=True, kw_only=True)
class ConversationRevisionServiceV2:
    transaction: ConversationRevisionTransactionProtocolV2
    cache: ConversationCacheInvalidatorProtocolV2

    async def fork_conversation(
        self,
        *,
        conversation_id: str,
        branch_message_id: str,
        tenant_id: str,
        user_id: str,
    ) -> ForkedConversationV2:
        return await self.transaction.fork_conversation(
            conversation_id=conversation_id,
            branch_message_id=branch_message_id,
            tenant_id=tenant_id,
            user_id=user_id,
        )

    async def edit_message(
        self,
        *,
        conversation_id: str,
        message_id: str,
        content: str | None,
        tenant_id: str,
        user_id: str,
    ) -> EditedConversationMessageV2:
        return await self.transaction.edit_message(
            conversation_id=conversation_id,
            message_id=message_id,
            content=content,
            tenant_id=tenant_id,
            user_id=user_id,
        )

    async def request_tool_undo(
        self,
        *,
        conversation_id: str,
        execution_id: str,
        tenant_id: str,
        user_id: str,
    ) -> ToolUndoRequestV2:
        return await self.transaction.request_tool_undo(
            conversation_id=conversation_id,
            execution_id=execution_id,
            tenant_id=tenant_id,
            user_id=user_id,
        )

    async def after_mutation_committed(self, project_id: str) -> None:
        await self.cache.invalidate(project_id)


@runtime_checkable
class ConversationRevisionResolverProtocolV2(Protocol):
    def resolve(self, operation: OperationContextV2) -> ConversationRevisionServiceV2: ...


@dataclass(frozen=True, kw_only=True)
class ConversationRevisionResolverV2:
    provider: ConversationRevisionProviderProtocolV2
    redis: RedisRuntimeServiceV2

    def resolve(self, operation: OperationContextV2) -> ConversationRevisionServiceV2:
        return ConversationRevisionServiceV2(
            transaction=self.provider.build(operation),
            cache=RedisConversationCacheInvalidatorV2(redis=self.redis),
        )


def _apply_conversation_revision_provider_v2(
    context: ContextV2,
    config: Mapping[str, Any],
) -> None:
    strategy = config.get("strategy")
    if strategy != "request-async-session":
        raise ValueError("conversation revision Provider requires strategy request-async-session")
    _ = context.provide(
        CONVERSATION_REVISION_PROVIDER_SERVICE_V2,
        SqlConversationRevisionProviderV2(strategy=strategy),
        label="conversation-revision-provider",
    )


def _apply_conversation_revision_v2(
    context: ContextV2,
    config: Mapping[str, Any],
) -> None:
    if config.get("strategy") != "operation-scoped-provider":
        raise ValueError("conversation revision requires strategy operation-scoped-provider")
    provider = context.require(CONVERSATION_REVISION_PROVIDER_INJECT_V2)
    if not isinstance(provider, ConversationRevisionProviderProtocolV2):
        raise RuntimeV2Error(
            "invalid_conversation_revision_provider",
            "conversation revision Provider has an invalid implementation",
        )
    redis = context.require(CONVERSATION_REVISION_REDIS_INJECT_V2)
    if not isinstance(redis, RedisRuntimeServiceV2):
        raise RuntimeV2Error(
            "invalid_conversation_revision_redis",
            "conversation revision Redis inject has an invalid implementation",
        )
    if redis.client is not None and not isinstance(redis.client, ConversationCacheClientProtocolV2):
        raise RuntimeV2Error(
            "invalid_conversation_cache_client",
            "conversation revision cache invalidation requires Redis scan_iter/delete",
        )
    _ = context.provide(
        CONVERSATION_REVISION_SERVICE_V2,
        ConversationRevisionResolverV2(provider=provider, redis=redis),
        label="conversation-revision",
    )


def conversation_revision_definitions_v2() -> tuple[PluginDefinitionV2, ...]:
    return (
        PluginDefinitionV2(
            module_ref=CONVERSATION_REVISION_PROVIDER_MODULE_V2,
            contract_digest=generated_contract_digest_v2(CONVERSATION_REVISION_PROVIDER_MODULE_V2),
            apply=_apply_conversation_revision_provider_v2,
        ),
        PluginDefinitionV2(
            module_ref=CONVERSATION_REVISION_MODULE_V2,
            contract_digest=generated_contract_digest_v2(CONVERSATION_REVISION_MODULE_V2),
            apply=_apply_conversation_revision_v2,
        ),
    )


__all__ = [
    "CONVERSATION_REVISION_MODULE_V2",
    "CONVERSATION_REVISION_PROVIDER_INJECT_V2",
    "CONVERSATION_REVISION_PROVIDER_MODULE_V2",
    "CONVERSATION_REVISION_PROVIDER_SERVICE_V2",
    "CONVERSATION_REVISION_REDIS_INJECT_V2",
    "CONVERSATION_REVISION_SERVICE_V2",
    "MODEL_MESSAGE_REVISED_EVENT_V2",
    "ConversationRevisionAccessDeniedV2",
    "ConversationRevisionConversationNotFoundV2",
    "ConversationRevisionErrorV2",
    "ConversationRevisionMessageNotFoundV2",
    "ConversationRevisionProviderProtocolV2",
    "ConversationRevisionResolverProtocolV2",
    "ConversationRevisionResolverV2",
    "ConversationRevisionServiceV2",
    "ConversationRevisionToolExecutionNotFoundV2",
    "ConversationRevisionTransactionProtocolV2",
    "EditedConversationMessageV2",
    "ForkedConversationV2",
    "SqlConversationRevisionProviderV2",
    "SqlConversationRevisionTransactionV2",
    "ToolUndoRequestV2",
    "conversation_revision_definitions_v2",
]
