"""Generation-owned title and summary application services."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal, Protocol, cast, runtime_checkable

from src.domain.model.agent import Conversation

from .conversation_access_services import (
    ConversationAccessResolverProtocolV2,
    ConversationAccessServiceV2,
)
from .conversation_enrichment_judge import (
    ConversationEnrichmentJudgeProtocolV2,
    ConversationEnrichmentJudgeResolverProtocolV2,
    ConversationEnrichmentMessageV2,
    ConversationEnrichmentResultV2,
)
from .runtime import (
    ContextV2,
    OperationContextV2,
    PluginDefinitionV2,
    RuntimeV2Error,
    generated_contract_digest_v2,
)

CONVERSATION_GENERATION_MODULE_V2 = "builtin://memstack/application/conversation-generation"
CONVERSATION_GENERATION_SERVICE_V2 = "service:application.conversation-generation"
CONVERSATION_GENERATION_ACCESS_INJECT_V2 = "conversation_access"
CONVERSATION_GENERATION_SESSION_LOG_INJECT_V2 = "session_log"
CONVERSATION_GENERATION_ENRICHMENT_JUDGE_INJECT_V2 = "enrichment_judge"

_OPERATION_IDENTITY_SERVICE_V2 = "service:operation.identity"
_CONVERSATION_MESSAGE_ROLES = frozenset({"assistant", "user"})
_DEFAULT_CONVERSATION_TITLES_V2 = frozenset({"New Chat", "New Conversation"})
_INITIAL_TITLE_MAX_MESSAGE_COUNT_V2 = 4


class ConversationGenerationSourceMissingV2(RuntimeError):
    """Raised when a requested generation has no eligible persisted messages."""

    def __init__(self, purpose: Literal["title", "summary"]) -> None:
        self.purpose = purpose
        super().__init__(f"conversation {purpose} generation requires persisted messages")


def _project_model_message_v2(raw_message: object) -> ConversationEnrichmentMessageV2 | None:
    if not isinstance(raw_message, Mapping):
        return None
    message = cast(Mapping[str, object], raw_message)
    role = message.get("role")
    content = message.get("content")
    if role not in _CONVERSATION_MESSAGE_ROLES or not isinstance(content, str) or not content:
        return None
    return ConversationEnrichmentMessageV2(
        role=cast(Literal["assistant", "user"], role),
        content=content,
    )


@runtime_checkable
class ConversationSessionLogReaderProtocolV2(Protocol):
    async def materialize_model_messages(
        self,
        *,
        conversation_id: str,
    ) -> list[dict[str, Any]]: ...


@dataclass(frozen=True, kw_only=True)
class ConversationGenerationServiceV2:
    """Operation-owned conversation enrichment with exact request identity."""

    access: ConversationAccessServiceV2
    session_log: ConversationSessionLogReaderProtocolV2
    enrichment_judge: ConversationEnrichmentJudgeProtocolV2
    tenant_id: str
    project_id: str
    user_id: str

    async def generate_title(self, *, conversation_id: str) -> Conversation | None:
        conversation = await self._scoped_conversation(conversation_id)
        if conversation is None:
            return None
        return await self._generate_title(conversation)

    async def generate_initial_title(self, *, conversation_id: str) -> Conversation | None:
        """Generate once for an early conversation that still has a default title."""
        conversation = await self._scoped_conversation(conversation_id)
        if conversation is None:
            return None
        if conversation.title not in _DEFAULT_CONVERSATION_TITLES_V2:
            return None
        if conversation.message_count > _INITIAL_TITLE_MAX_MESSAGE_COUNT_V2:
            return None
        return await self._generate_title(conversation)

    async def _generate_title(self, conversation: Conversation) -> Conversation:
        raw_messages = await self.session_log.materialize_model_messages(
            conversation_id=conversation.id,
        )
        first_user_message = next(
            (
                message
                for raw_message in raw_messages
                if (message := _project_model_message_v2(raw_message)) is not None
                and message.role == "user"
            ),
            None,
        )
        if first_user_message is None:
            raise ConversationGenerationSourceMissingV2("title")

        judgment = await self.enrichment_judge.judge(
            purpose="title",
            conversation_id=conversation.id,
            messages=(first_user_message,),
        )
        if not isinstance(judgment, ConversationEnrichmentResultV2):
            raise RuntimeV2Error(
                "invalid_conversation_enrichment_result",
                "conversation enrichment judge returned an invalid result",
            )
        conversation.update_title(judgment.value)
        return await self._save(conversation)

    async def generate_summary(self, *, conversation_id: str) -> Conversation | None:
        conversation = await self._scoped_conversation(conversation_id)
        if conversation is None:
            return None
        raw_messages = await self.session_log.materialize_model_messages(
            conversation_id=conversation.id,
        )
        messages = tuple(
            message
            for raw_message in raw_messages
            if (message := _project_model_message_v2(raw_message)) is not None
        )
        if not messages:
            raise ConversationGenerationSourceMissingV2("summary")

        judgment = await self.enrichment_judge.judge(
            purpose="summary",
            conversation_id=conversation.id,
            messages=messages,
        )
        if not isinstance(judgment, ConversationEnrichmentResultV2):
            raise RuntimeV2Error(
                "invalid_conversation_enrichment_result",
                "conversation enrichment judge returned an invalid result",
            )
        conversation.summary = judgment.value
        conversation.updated_at = datetime.now(UTC)
        return await self._save(conversation)

    async def after_update_committed(self) -> None:
        """Invalidate generation-owned conversation caches after durable commit."""
        await self.access.cache.invalidate(self.project_id)

    async def _scoped_conversation(self, conversation_id: str) -> Conversation | None:
        conversation = await self.access.get_conversation(
            conversation_id=conversation_id,
            project_id=self.project_id,
            user_id=self.user_id,
        )
        if conversation is None or conversation.tenant_id != self.tenant_id:
            return None
        return conversation

    async def _save(self, conversation: Conversation) -> Conversation:
        saved = await self.access.save_scoped_conversation(
            conversation=conversation,
            project_id=self.project_id,
            tenant_id=self.tenant_id,
            user_id=self.user_id,
        )
        if saved is None:
            raise RuntimeV2Error(
                "conversation_generation_persistence_failed",
                "conversation enrichment could not persist its scoped result",
            )
        return saved


@runtime_checkable
class ConversationGenerationResolverProtocolV2(Protocol):
    """Resolve generation services from one operation boundary."""

    def resolve(self, operation: OperationContextV2) -> ConversationGenerationServiceV2: ...


@dataclass(frozen=True, kw_only=True)
class ConversationGenerationResolverV2:
    conversation_access: ConversationAccessResolverProtocolV2
    session_log: ConversationSessionLogReaderProtocolV2
    enrichment_judge: ConversationEnrichmentJudgeResolverProtocolV2

    def resolve(self, operation: OperationContextV2) -> ConversationGenerationServiceV2:
        tenant_id, project_id, user_id = _operation_identity_v2(operation)
        return ConversationGenerationServiceV2(
            access=self.conversation_access.resolve(operation),
            session_log=self.session_log,
            enrichment_judge=self.enrichment_judge.resolve(operation),
            tenant_id=tenant_id,
            project_id=project_id,
            user_id=user_id,
        )


def _operation_identity_v2(operation: OperationContextV2) -> tuple[str, str, str]:
    identity = operation.require(_OPERATION_IDENTITY_SERVICE_V2)
    if not isinstance(identity, Mapping):
        raise RuntimeV2Error(
            "invalid_operation_identity",
            "conversation generation requires operation identity metadata",
        )
    values = cast(Mapping[str, object], identity)
    tenant_id = values.get("tenant_id")
    project_id = values.get("project_id")
    user_id = values.get("user_id")
    if not all(isinstance(value, str) and value for value in (tenant_id, project_id, user_id)):
        raise RuntimeV2Error(
            "invalid_operation_identity",
            "conversation generation requires tenant, project, and user identity",
        )
    tenant_id = cast(str, tenant_id)
    project_id = cast(str, project_id)
    user_id = cast(str, user_id)
    scope = operation.context.scope
    if scope.tenant_id != tenant_id or scope.project_id != project_id:
        raise RuntimeV2Error(
            "operation_identity_scope_mismatch",
            "conversation generation identity does not match its operation scope",
        )
    return tenant_id, project_id, user_id


def _apply_conversation_generation_v2(
    context: ContextV2,
    config: Mapping[str, Any],
) -> None:
    if config.get("strategy") != "operation-scoped-provider":
        raise ValueError("conversation generation requires strategy operation-scoped-provider")
    conversation_access = context.require(CONVERSATION_GENERATION_ACCESS_INJECT_V2)
    if not isinstance(conversation_access, ConversationAccessResolverProtocolV2):
        raise RuntimeV2Error(
            "invalid_conversation_generation_access",
            "conversation generation requires a conversation access resolver",
        )
    session_log = context.require(CONVERSATION_GENERATION_SESSION_LOG_INJECT_V2)
    if not isinstance(session_log, ConversationSessionLogReaderProtocolV2):
        raise RuntimeV2Error(
            "invalid_conversation_generation_session_log",
            "conversation generation requires an ordered session-log reader",
        )
    enrichment_judge = context.require(CONVERSATION_GENERATION_ENRICHMENT_JUDGE_INJECT_V2)
    if not isinstance(enrichment_judge, ConversationEnrichmentJudgeResolverProtocolV2):
        raise RuntimeV2Error(
            "invalid_conversation_generation_enrichment_judge",
            "conversation generation requires an enrichment judge resolver",
        )
    _ = context.provide(
        CONVERSATION_GENERATION_SERVICE_V2,
        ConversationGenerationResolverV2(
            conversation_access=conversation_access,
            session_log=session_log,
            enrichment_judge=enrichment_judge,
        ),
        label="conversation-generation",
    )


def conversation_generation_definition_v2() -> PluginDefinitionV2:
    return PluginDefinitionV2(
        module_ref=CONVERSATION_GENERATION_MODULE_V2,
        contract_digest=generated_contract_digest_v2(CONVERSATION_GENERATION_MODULE_V2),
        apply=_apply_conversation_generation_v2,
    )


__all__ = [
    "CONVERSATION_GENERATION_ACCESS_INJECT_V2",
    "CONVERSATION_GENERATION_ENRICHMENT_JUDGE_INJECT_V2",
    "CONVERSATION_GENERATION_MODULE_V2",
    "CONVERSATION_GENERATION_SERVICE_V2",
    "CONVERSATION_GENERATION_SESSION_LOG_INJECT_V2",
    "ConversationGenerationResolverProtocolV2",
    "ConversationGenerationResolverV2",
    "ConversationGenerationServiceV2",
    "ConversationGenerationSourceMissingV2",
    "ConversationSessionLogReaderProtocolV2",
    "conversation_generation_definition_v2",
]
