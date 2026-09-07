"""Generation-owned application seam for Agent execution resume."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from src.application.services.agent.execution_resume_service import (
    ExecutionResumeService,
    ResumeContext,
)

from .conversation_access_services import ConversationCrudRepositoryFactoryProtocolV2
from .runtime import (
    ContextV2,
    OperationContextV2,
    PluginDefinitionV2,
    RuntimeV2Error,
    generated_contract_digest_v2,
)

AGENT_EXECUTION_RESUME_MODULE_V2 = "builtin://memstack/application/agent-execution-resume"
AGENT_EXECUTION_RESUME_SERVICE_V2 = "service:application.agent-execution-resume"
AGENT_EXECUTION_RESUME_REPOSITORIES_INJECT_V2 = "repositories"


@runtime_checkable
class AgentExecutionResumeServiceProtocolV2(Protocol):
    """Application methods exposed to request authorities."""

    async def can_resume(self, conversation_id: str) -> bool: ...

    async def get_resume_context(self, conversation_id: str) -> ResumeContext | None: ...

    async def prepare_resume_request(
        self,
        conversation_id: str,
        override_message: str | None = None,
    ) -> dict[str, Any] | None: ...

    async def mark_resumed(self, conversation_id: str, checkpoint_id: str) -> None: ...


@runtime_checkable
class AgentExecutionResumeResolverProtocolV2(Protocol):
    """Resolve one execution resume service from declared Provider aliases."""

    def resolve(
        self,
        operation: OperationContextV2,
    ) -> AgentExecutionResumeServiceProtocolV2: ...


@dataclass(frozen=True, kw_only=True)
class AgentExecutionResumeResolverV2:
    """Compose execution resume from the operation-owned checkpoint repository."""

    repositories: ConversationCrudRepositoryFactoryProtocolV2

    def resolve(self, operation: OperationContextV2) -> AgentExecutionResumeServiceProtocolV2:
        repositories = self.repositories.build_crud(operation)
        return ExecutionResumeService(
            checkpoint_repo=repositories.execution_checkpoint,
        )


def _apply_agent_execution_resume_v2(
    context: ContextV2,
    config: Mapping[str, Any],
) -> None:
    if config.get("strategy") != "operation-scoped-provider":
        raise ValueError("Agent execution resume requires strategy operation-scoped-provider")
    repositories = context.require(AGENT_EXECUTION_RESUME_REPOSITORIES_INJECT_V2)
    if not isinstance(repositories, ConversationCrudRepositoryFactoryProtocolV2):
        raise RuntimeV2Error(
            "invalid_agent_execution_resume_repository_provider",
            "Agent execution resume repository Provider has an invalid implementation",
        )
    _ = context.provide(
        AGENT_EXECUTION_RESUME_SERVICE_V2,
        AgentExecutionResumeResolverV2(repositories=repositories),
        label="agent-execution-resume",
    )


def agent_execution_resume_definition_v2() -> PluginDefinitionV2:
    """Return the execution resume application Consumer definition."""
    return PluginDefinitionV2(
        module_ref=AGENT_EXECUTION_RESUME_MODULE_V2,
        contract_digest=generated_contract_digest_v2(AGENT_EXECUTION_RESUME_MODULE_V2),
        apply=_apply_agent_execution_resume_v2,
    )


__all__ = [
    "AGENT_EXECUTION_RESUME_MODULE_V2",
    "AGENT_EXECUTION_RESUME_REPOSITORIES_INJECT_V2",
    "AGENT_EXECUTION_RESUME_SERVICE_V2",
    "AgentExecutionResumeResolverProtocolV2",
    "AgentExecutionResumeResolverV2",
    "AgentExecutionResumeServiceProtocolV2",
    "agent_execution_resume_definition_v2",
]
