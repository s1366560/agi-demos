# pyright: reportImportCycles=false
"""Generation-owned application seam for conversation participant rosters."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol, cast, runtime_checkable
from uuid import uuid4

from src.domain.model.agent import Conversation
from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.domain.model.project.project import Project

from .agent_definition import AgentDefinitionResolverProtocolV2
from .conversation_access_services import (
    ConversationAccessResolverProtocolV2,
    ConversationAccessServiceV2,
)
from .project_tenant_services import (
    ProjectTenantApplicationResolverProtocolV2,
    ProjectTenantServicesV2,
)
from .runtime import (
    ContextV2,
    OperationContextV2,
    PluginDefinitionV2,
    RuntimeV2Error,
    generated_contract_digest_v2,
)

CONVERSATION_PARTICIPANT_MODULE_V2 = "builtin://memstack/application/conversation-participants"
CONVERSATION_PARTICIPANT_SERVICE_V2 = "service:application.conversation-participants"
CONVERSATION_PARTICIPANT_ACCESS_INJECT_V2 = "conversation_access"
CONVERSATION_PARTICIPANT_PROJECT_TENANT_INJECT_V2 = "project_tenant"
CONVERSATION_PARTICIPANT_AGENT_DEFINITIONS_INJECT_V2 = "agent_definitions"


class ConversationParticipantErrorV2(RuntimeError):
    """Base failure for the participant application seam."""


class ConversationParticipantConversationNotFoundV2(ConversationParticipantErrorV2):
    """The requested conversation does not exist."""


class ConversationParticipantProjectNotFoundV2(ConversationParticipantErrorV2):
    """The project referenced by the conversation does not exist."""


class ConversationParticipantScopeMismatchV2(ConversationParticipantErrorV2):
    """A participant mutation or lookup escaped its exact tenant/project scope."""


@dataclass(frozen=True, kw_only=True)
class ConversationParticipantRecordV2:
    conversation: Conversation
    project: Project


@dataclass(frozen=True, kw_only=True)
class ConversationParticipantServiceV2:
    """Operation-owned participant roster persistence and Agent Definition authority."""

    operation: OperationContextV2
    access: ConversationAccessServiceV2
    project_tenant: ProjectTenantServicesV2
    agent_definitions: AgentDefinitionResolverProtocolV2

    async def load(self, conversation_id: str) -> ConversationParticipantRecordV2:
        if not conversation_id.strip():
            raise ValueError("conversation_id must be non-empty")
        conversation = await self.access.find_by_id(conversation_id)
        if conversation is None:
            raise ConversationParticipantConversationNotFoundV2(conversation_id)
        scope = self.operation.context.scope
        if scope.tenant_id is None or conversation.tenant_id != scope.tenant_id:
            raise ConversationParticipantConversationNotFoundV2(conversation_id)
        if scope.project_id not in (None, conversation.project_id):
            raise ConversationParticipantConversationNotFoundV2(conversation_id)
        project = await self.project_tenant.project_repository.find_by_id(conversation.project_id)
        if project is None or project.tenant_id != scope.tenant_id:
            raise ConversationParticipantProjectNotFoundV2(conversation.project_id)
        return ConversationParticipantRecordV2(
            conversation=conversation,
            project=project,
        )

    async def resolve_agent(
        self,
        *,
        agent_id: str,
        tenant_id: str,
        project_id: str,
    ) -> object | None:
        """Resolve one exact Agent Definition in a project-scoped operation overlay."""
        _require_identifier(agent_id, field_name="agent_id")
        _require_identifier(tenant_id, field_name="tenant_id")
        _require_identifier(project_id, field_name="project_id")
        self._assert_operation_scope(tenant_id=tenant_id, project_id=project_id)

        from .boundary import (
            OPERATION_DB_SESSION_SERVICE_V2,
            OPERATION_IDENTITY_SERVICE_V2,
            OPERATION_METADATA_SERVICE_V2,
            bind_operation_context_v2,
        )

        child = OperationContextV2(
            generation=self.operation.generation,
            operation_id=f"{self.operation.operation_id}:agent-definition:{uuid4()}",
            scope=ScopeV2(
                kind=ScopeKindV2.PROJECT,
                tenant_id=tenant_id,
                project_id=project_id,
            ),
        )
        async with child:
            _ = child.provide(
                OPERATION_DB_SESSION_SERVICE_V2,
                self.operation.require(OPERATION_DB_SESSION_SERVICE_V2),
            )
            _ = child.provide(
                OPERATION_IDENTITY_SERVICE_V2,
                _project_identity(self.operation, tenant_id=tenant_id, project_id=project_id),
            )
            _ = child.provide(
                OPERATION_METADATA_SERVICE_V2,
                {
                    "kind": "conversation-participant-agent-definition",
                    "parent_operation_id": self.operation.operation_id,
                },
            )
            with bind_operation_context_v2(child):
                return await self.agent_definitions.resolve(
                    agent_id=agent_id,
                    tenant_id=tenant_id,
                    project_id=project_id,
                )

    async def save(
        self,
        conversation: Conversation,
        *,
        tenant_id: str,
        project_id: str,
    ) -> Conversation:
        """Persist only an aggregate that still belongs to the authorized scope."""
        self._assert_operation_scope(tenant_id=tenant_id, project_id=project_id)
        if conversation.tenant_id != tenant_id or conversation.project_id != project_id:
            raise ConversationParticipantScopeMismatchV2(conversation.id)
        return await self.access.repository.save(conversation)

    async def after_mutation_committed(self, project_id: str) -> None:
        """Invalidate transitional list/count caches only after a durable commit."""
        await self.access.cache.invalidate(project_id)

    def _assert_operation_scope(self, *, tenant_id: str, project_id: str) -> None:
        scope = self.operation.context.scope
        if scope.tenant_id != tenant_id or scope.project_id not in (None, project_id):
            raise ConversationParticipantScopeMismatchV2(project_id)


@runtime_checkable
class ConversationParticipantResolverProtocolV2(Protocol):
    def resolve(self, operation: OperationContextV2) -> ConversationParticipantServiceV2: ...


@dataclass(frozen=True, kw_only=True)
class ConversationParticipantResolverV2:
    conversation_access: ConversationAccessResolverProtocolV2
    project_tenant: ProjectTenantApplicationResolverProtocolV2
    agent_definitions: AgentDefinitionResolverProtocolV2

    def resolve(self, operation: OperationContextV2) -> ConversationParticipantServiceV2:
        return ConversationParticipantServiceV2(
            operation=operation,
            access=self.conversation_access.resolve(operation),
            project_tenant=self.project_tenant.resolve(operation),
            agent_definitions=self.agent_definitions,
        )


def _project_identity(
    operation: OperationContextV2,
    *,
    tenant_id: str,
    project_id: str,
) -> dict[str, str]:
    from .boundary import OPERATION_IDENTITY_SERVICE_V2

    raw_identity = operation.require(OPERATION_IDENTITY_SERVICE_V2)
    if not isinstance(raw_identity, Mapping):
        raise RuntimeV2Error(
            "invalid_operation_identity",
            "conversation participant identity must be an object",
        )
    identity_mapping = cast("Mapping[str, object]", raw_identity)
    if identity_mapping.get("tenant_id") != tenant_id:
        raise ConversationParticipantScopeMismatchV2(project_id)
    identity = {"tenant_id": tenant_id, "project_id": project_id}
    user_id = identity_mapping.get("user_id")
    if isinstance(user_id, str) and user_id:
        identity["user_id"] = user_id
    return identity


def _require_identifier(value: str, *, field_name: str) -> None:
    if not value.strip():
        raise ValueError(f"{field_name} must be non-empty")


def _apply_conversation_participant_v2(
    context: ContextV2,
    config: Mapping[str, Any],
) -> None:
    if config.get("strategy") != "operation-scoped-provider":
        raise ValueError("conversation participants require strategy operation-scoped-provider")
    conversation_access = context.require(CONVERSATION_PARTICIPANT_ACCESS_INJECT_V2)
    if not isinstance(conversation_access, ConversationAccessResolverProtocolV2):
        raise RuntimeV2Error(
            "invalid_conversation_participant_access",
            "conversation participants require a conversation access resolver",
        )
    project_tenant = context.require(CONVERSATION_PARTICIPANT_PROJECT_TENANT_INJECT_V2)
    if not isinstance(project_tenant, ProjectTenantApplicationResolverProtocolV2):
        raise RuntimeV2Error(
            "invalid_conversation_participant_project_tenant",
            "conversation participants require a project/tenant resolver",
        )
    agent_definitions = context.require(CONVERSATION_PARTICIPANT_AGENT_DEFINITIONS_INJECT_V2)
    if not isinstance(agent_definitions, AgentDefinitionResolverProtocolV2):
        raise RuntimeV2Error(
            "invalid_conversation_participant_agent_definitions",
            "conversation participants require an Agent Definition resolver",
        )
    _ = context.provide(
        CONVERSATION_PARTICIPANT_SERVICE_V2,
        ConversationParticipantResolverV2(
            conversation_access=conversation_access,
            project_tenant=project_tenant,
            agent_definitions=agent_definitions,
        ),
        label="conversation-participants",
    )


def conversation_participant_definition_v2() -> PluginDefinitionV2:
    return PluginDefinitionV2(
        module_ref=CONVERSATION_PARTICIPANT_MODULE_V2,
        contract_digest=generated_contract_digest_v2(CONVERSATION_PARTICIPANT_MODULE_V2),
        apply=_apply_conversation_participant_v2,
    )


__all__ = [
    "CONVERSATION_PARTICIPANT_ACCESS_INJECT_V2",
    "CONVERSATION_PARTICIPANT_AGENT_DEFINITIONS_INJECT_V2",
    "CONVERSATION_PARTICIPANT_MODULE_V2",
    "CONVERSATION_PARTICIPANT_PROJECT_TENANT_INJECT_V2",
    "CONVERSATION_PARTICIPANT_SERVICE_V2",
    "ConversationParticipantConversationNotFoundV2",
    "ConversationParticipantErrorV2",
    "ConversationParticipantProjectNotFoundV2",
    "ConversationParticipantRecordV2",
    "ConversationParticipantResolverProtocolV2",
    "ConversationParticipantResolverV2",
    "ConversationParticipantScopeMismatchV2",
    "ConversationParticipantServiceV2",
    "conversation_participant_definition_v2",
]
