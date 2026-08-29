"""Generation-owned application seam for conversation configuration mutations."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from src.domain.model.agent import Conversation

from .agent_definition import AgentDefinitionResolverProtocolV2
from .conversation_access_services import (
    ConversationAccessResolverProtocolV2,
    ConversationAccessServiceV2,
)
from .conversation_collection_services import InvalidConversationAgentSelectionV2
from .runtime import (
    ContextV2,
    OperationContextV2,
    PluginDefinitionV2,
    RuntimeV2Error,
    generated_contract_digest_v2,
)

CONVERSATION_CONFIG_MODULE_V2 = "builtin://memstack/application/conversation-config"
CONVERSATION_CONFIG_SERVICE_V2 = "service:application.conversation-config"
CONVERSATION_CONFIG_CONVERSATION_ACCESS_INJECT_V2 = "conversation_access"
CONVERSATION_CONFIG_AGENT_DEFINITIONS_INJECT_V2 = "agent_definitions"


@dataclass(frozen=True, kw_only=True)
class ConversationConfigPatchV2:
    """Explicit-presence patch independent of the HTTP request schema."""

    selected_agent_id_present: bool = False
    selected_agent_id: str | None = None
    llm_model_override_present: bool = False
    llm_model_override: str | None = None
    llm_overrides_present: bool = False
    llm_overrides: Mapping[str, Any] | None = None


@dataclass(frozen=True, kw_only=True)
class ConversationConfigServiceV2:
    """Operation-owned configuration mutation authority."""

    access: ConversationAccessServiceV2
    agent_definitions: AgentDefinitionResolverProtocolV2

    async def update_conversation_config(
        self,
        *,
        conversation_id: str,
        project_id: str,
        tenant_id: str,
        user_id: str,
        patch: ConversationConfigPatchV2,
    ) -> Conversation | None:
        conversation = await self.access.get_conversation(
            conversation_id=conversation_id,
            project_id=project_id,
            user_id=user_id,
        )
        if conversation is None or conversation.tenant_id != tenant_id:
            return None

        config_patch: dict[str, Any] = {}
        if patch.selected_agent_id_present:
            selected_agent_id = patch.selected_agent_id.strip() if patch.selected_agent_id else ""
            if selected_agent_id:
                definition = await self.agent_definitions.resolve(
                    agent_id=selected_agent_id,
                    tenant_id=tenant_id,
                    project_id=project_id,
                )
                if definition is None:
                    raise InvalidConversationAgentSelectionV2(selected_agent_id)
            config_patch["selected_agent_id"] = selected_agent_id or None
        if patch.llm_model_override_present:
            model_override = patch.llm_model_override.strip() if patch.llm_model_override else ""
            config_patch["llm_model_override"] = model_override or None
        if patch.llm_overrides_present:
            cleaned_overrides = {
                key: value
                for key, value in (patch.llm_overrides or {}).items()
                if value is not None
            }
            config_patch["llm_overrides"] = cleaned_overrides or None

        conversation.update_agent_config(config_patch)
        return await self.access.save_scoped_conversation(
            conversation=conversation,
            project_id=project_id,
            tenant_id=tenant_id,
            user_id=user_id,
        )

    async def after_update_committed(self, project_id: str) -> None:
        """Invalidate generation-owned conversation caches after durable commit."""
        await self.access.cache.invalidate(project_id)


@runtime_checkable
class ConversationConfigResolverProtocolV2(Protocol):
    """Resolve config mutation services from one operation boundary."""

    def resolve(self, operation: OperationContextV2) -> ConversationConfigServiceV2: ...


@dataclass(frozen=True, kw_only=True)
class ConversationConfigResolverV2:
    conversation_access: ConversationAccessResolverProtocolV2
    agent_definitions: AgentDefinitionResolverProtocolV2

    def resolve(self, operation: OperationContextV2) -> ConversationConfigServiceV2:
        return ConversationConfigServiceV2(
            access=self.conversation_access.resolve(operation),
            agent_definitions=self.agent_definitions,
        )


def _apply_conversation_config_v2(
    context: ContextV2,
    config: Mapping[str, Any],
) -> None:
    if config.get("strategy") != "operation-scoped-provider":
        raise ValueError("conversation config requires strategy operation-scoped-provider")
    conversation_access = context.require(CONVERSATION_CONFIG_CONVERSATION_ACCESS_INJECT_V2)
    if not isinstance(conversation_access, ConversationAccessResolverProtocolV2):
        raise RuntimeV2Error(
            "invalid_conversation_config_access",
            "conversation config requires a conversation access resolver",
        )
    agent_definitions = context.require(CONVERSATION_CONFIG_AGENT_DEFINITIONS_INJECT_V2)
    if not isinstance(agent_definitions, AgentDefinitionResolverProtocolV2):
        raise RuntimeV2Error(
            "invalid_conversation_config_agent_definitions",
            "conversation config requires an agent-definition resolver",
        )
    _ = context.provide(
        CONVERSATION_CONFIG_SERVICE_V2,
        ConversationConfigResolverV2(
            conversation_access=conversation_access,
            agent_definitions=agent_definitions,
        ),
        label="conversation-config",
    )


def conversation_config_definition_v2() -> PluginDefinitionV2:
    return PluginDefinitionV2(
        module_ref=CONVERSATION_CONFIG_MODULE_V2,
        contract_digest=generated_contract_digest_v2(CONVERSATION_CONFIG_MODULE_V2),
        apply=_apply_conversation_config_v2,
    )


__all__ = [
    "CONVERSATION_CONFIG_AGENT_DEFINITIONS_INJECT_V2",
    "CONVERSATION_CONFIG_CONVERSATION_ACCESS_INJECT_V2",
    "CONVERSATION_CONFIG_MODULE_V2",
    "CONVERSATION_CONFIG_SERVICE_V2",
    "ConversationConfigPatchV2",
    "ConversationConfigResolverProtocolV2",
    "ConversationConfigResolverV2",
    "ConversationConfigServiceV2",
    "conversation_config_definition_v2",
]
