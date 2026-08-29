"""Generation-owned persistence and application seams for conversation context status."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.agent import Conversation
from src.domain.model.agent.conversation.context_summary import ContextSummary
from src.domain.ports.agent.context_manager_port import ContextSummaryPort
from src.infrastructure.adapters.secondary.persistence.sql_context_summary_adapter import (
    SqlContextSummaryAdapter,
)

from .conversation_access_services import (
    ConversationAccessResolverProtocolV2,
    ConversationAccessServiceV2,
)
from .runtime import (
    ContextV2,
    OperationContextV2,
    PluginDefinitionV2,
    RuntimeV2Error,
    generated_contract_digest_v2,
)

CONTEXT_SUMMARY_PROVIDER_MODULE_V2 = "builtin://memstack/persistence/context-summary-provider"
CONTEXT_SUMMARY_PROVIDER_SERVICE_V2 = "service:persistence.context-summary-provider"
CONVERSATION_CONTEXT_STATUS_MODULE_V2 = "builtin://memstack/application/conversation-context-status"
CONVERSATION_CONTEXT_STATUS_SERVICE_V2 = "service:application.conversation-context-status"
CONVERSATION_CONTEXT_STATUS_ACCESS_INJECT_V2 = "conversation_access"
CONVERSATION_CONTEXT_STATUS_SUMMARIES_INJECT_V2 = "context_summaries"

_OPERATION_DB_SESSION_SERVICE_V2 = "service:operation.db-session"


@runtime_checkable
class ContextSummaryProviderProtocolV2(Protocol):
    """Build the context-summary port from one operation-owned DB session."""

    def build(self, operation: OperationContextV2) -> ContextSummaryPort: ...


@dataclass(frozen=True, kw_only=True)
class SqlContextSummaryProviderV2:
    """Keep the SQL adapter behind an explicit persistence Provider."""

    strategy: str

    def build(self, operation: OperationContextV2) -> ContextSummaryPort:
        db = operation.require(_OPERATION_DB_SESSION_SERVICE_V2)
        if not isinstance(db, AsyncSession):
            raise RuntimeV2Error(
                "invalid_operation_db_session",
                "context summary persistence requires an AsyncSession operation service",
            )
        return SqlContextSummaryAdapter(db)


@dataclass(frozen=True, kw_only=True)
class ConversationContextStatusV2:
    """Stable public projection for the context-status HTTP response."""

    conversation_id: str
    message_count: int
    has_summary: bool
    summary_tokens: int
    messages_in_summary: int
    compression_level: str
    from_cache: bool

    @classmethod
    def from_conversation(
        cls,
        conversation: Conversation,
        summary: ContextSummary | None,
    ) -> ConversationContextStatusV2:
        if summary is None:
            return cls(
                conversation_id=conversation.id,
                message_count=conversation.message_count,
                has_summary=False,
                summary_tokens=0,
                messages_in_summary=0,
                compression_level="none",
                from_cache=False,
            )
        return cls(
            conversation_id=conversation.id,
            message_count=conversation.message_count,
            has_summary=True,
            summary_tokens=summary.summary_tokens,
            messages_in_summary=summary.messages_covered_count,
            compression_level=summary.compression_level,
            from_cache=True,
        )

    def to_dict(self) -> dict[str, str | int | bool]:
        """Return the existing wire shape without exposing persistence objects."""
        return {
            "conversation_id": self.conversation_id,
            "message_count": self.message_count,
            "has_summary": self.has_summary,
            "summary_tokens": self.summary_tokens,
            "messages_in_summary": self.messages_in_summary,
            "compression_level": self.compression_level,
            "from_cache": self.from_cache,
        }


@dataclass(frozen=True, kw_only=True)
class ConversationContextStatusServiceV2:
    """Operation-owned query authority for one scoped conversation."""

    access: ConversationAccessServiceV2
    summaries: ContextSummaryPort

    async def get_context_status(
        self,
        *,
        conversation_id: str,
        project_id: str,
        tenant_id: str,
        user_id: str,
    ) -> ConversationContextStatusV2 | None:
        if not tenant_id.strip():
            raise ValueError("tenant_id must be non-empty")
        conversation = await self.access.get_conversation(
            conversation_id=conversation_id,
            project_id=project_id,
            user_id=user_id,
        )
        if conversation is None or conversation.tenant_id != tenant_id:
            return None
        summary = await self.summaries.get_summary(conversation.id)
        return ConversationContextStatusV2.from_conversation(conversation, summary)


@runtime_checkable
class ConversationContextStatusResolverProtocolV2(Protocol):
    """Resolve context-status services from one operation boundary."""

    def resolve(self, operation: OperationContextV2) -> ConversationContextStatusServiceV2: ...


@dataclass(frozen=True, kw_only=True)
class ConversationContextStatusResolverV2:
    """Bind declared access and summary Providers to an operation."""

    conversation_access: ConversationAccessResolverProtocolV2
    context_summaries: ContextSummaryProviderProtocolV2

    def resolve(self, operation: OperationContextV2) -> ConversationContextStatusServiceV2:
        summaries = self.context_summaries.build(operation)
        if not isinstance(summaries, ContextSummaryPort):
            raise RuntimeV2Error(
                "invalid_context_summary_adapter",
                "context summary Provider returned an invalid implementation",
            )
        return ConversationContextStatusServiceV2(
            access=self.conversation_access.resolve(operation),
            summaries=summaries,
        )


def _apply_context_summary_provider_v2(
    context: ContextV2,
    config: Mapping[str, Any],
) -> None:
    strategy = config.get("strategy")
    if strategy != "request-async-session":
        raise ValueError("context summary Provider requires strategy request-async-session")
    _ = context.provide(
        CONTEXT_SUMMARY_PROVIDER_SERVICE_V2,
        SqlContextSummaryProviderV2(strategy=strategy),
        label="context-summary-provider",
    )


def _apply_conversation_context_status_v2(
    context: ContextV2,
    config: Mapping[str, Any],
) -> None:
    if config.get("strategy") != "operation-scoped-provider":
        raise ValueError("conversation context status requires strategy operation-scoped-provider")
    conversation_access = context.require(CONVERSATION_CONTEXT_STATUS_ACCESS_INJECT_V2)
    if not isinstance(conversation_access, ConversationAccessResolverProtocolV2):
        raise RuntimeV2Error(
            "invalid_conversation_context_status_access",
            "conversation context status requires a conversation access resolver",
        )
    context_summaries = context.require(CONVERSATION_CONTEXT_STATUS_SUMMARIES_INJECT_V2)
    if not isinstance(context_summaries, ContextSummaryProviderProtocolV2):
        raise RuntimeV2Error(
            "invalid_context_summary_provider",
            "context summary Provider has an invalid implementation",
        )
    _ = context.provide(
        CONVERSATION_CONTEXT_STATUS_SERVICE_V2,
        ConversationContextStatusResolverV2(
            conversation_access=conversation_access,
            context_summaries=context_summaries,
        ),
        label="conversation-context-status",
    )


def conversation_context_status_definitions_v2() -> tuple[PluginDefinitionV2, ...]:
    """Return the summary persistence Provider and explicit application Consumer."""
    return (
        PluginDefinitionV2(
            module_ref=CONTEXT_SUMMARY_PROVIDER_MODULE_V2,
            contract_digest=generated_contract_digest_v2(CONTEXT_SUMMARY_PROVIDER_MODULE_V2),
            apply=_apply_context_summary_provider_v2,
        ),
        PluginDefinitionV2(
            module_ref=CONVERSATION_CONTEXT_STATUS_MODULE_V2,
            contract_digest=generated_contract_digest_v2(CONVERSATION_CONTEXT_STATUS_MODULE_V2),
            apply=_apply_conversation_context_status_v2,
        ),
    )


__all__ = [
    "CONTEXT_SUMMARY_PROVIDER_MODULE_V2",
    "CONTEXT_SUMMARY_PROVIDER_SERVICE_V2",
    "CONVERSATION_CONTEXT_STATUS_ACCESS_INJECT_V2",
    "CONVERSATION_CONTEXT_STATUS_MODULE_V2",
    "CONVERSATION_CONTEXT_STATUS_SERVICE_V2",
    "CONVERSATION_CONTEXT_STATUS_SUMMARIES_INJECT_V2",
    "ContextSummaryProviderProtocolV2",
    "ConversationContextStatusResolverProtocolV2",
    "ConversationContextStatusResolverV2",
    "ConversationContextStatusServiceV2",
    "ConversationContextStatusV2",
    "SqlContextSummaryProviderV2",
    "conversation_context_status_definitions_v2",
]
