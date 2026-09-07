"""Generation-owned persistence and application seams for workflow patterns."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.ports.repositories.workflow_pattern_repository import (
    WorkflowPatternRepositoryPort,
)
from src.infrastructure.adapters.secondary.persistence.sql_workflow_pattern_repository import (
    SqlWorkflowPatternRepository,
)

from .runtime import (
    ContextV2,
    OperationContextV2,
    PluginDefinitionV2,
    RuntimeV2Error,
    generated_contract_digest_v2,
)

WORKFLOW_PATTERN_PROVIDER_MODULE_V2 = "builtin://memstack/persistence/workflow-pattern-provider"
WORKFLOW_PATTERN_PROVIDER_SERVICE_V2 = "service:persistence.workflow-pattern-provider"
WORKFLOW_PATTERN_APPLICATION_MODULE_V2 = "builtin://memstack/application/workflow-pattern-services"
WORKFLOW_PATTERN_APPLICATION_SERVICE_V2 = "service:application.workflow-pattern-services"
WORKFLOW_PATTERN_PROVIDER_INJECT_V2 = "provider"
_OPERATION_DB_SESSION_SERVICE_V2 = "service:operation.db-session"


@runtime_checkable
class WorkflowPatternRepositoryFactoryProtocolV2(Protocol):
    """Provider contract hiding concrete workflow-pattern persistence."""

    def build(self, operation: OperationContextV2) -> WorkflowPatternRepositoryPort: ...


@dataclass(frozen=True, kw_only=True)
class SqlWorkflowPatternRepositoryFactoryV2:
    """Bind the repository to the SQL session owned by one operation."""

    def build(self, operation: OperationContextV2) -> WorkflowPatternRepositoryPort:
        db = operation.require(_OPERATION_DB_SESSION_SERVICE_V2)
        if not isinstance(db, AsyncSession):
            raise RuntimeV2Error(
                "invalid_operation_db_session",
                "workflow-pattern services require an AsyncSession operation service",
            )
        return SqlWorkflowPatternRepository(db)


@dataclass(frozen=True, kw_only=True)
class WorkflowPatternApplicationServicesV2:
    """Request-owned workflow-pattern persistence resolved from one generation."""

    repository: WorkflowPatternRepositoryPort


@runtime_checkable
class WorkflowPatternApplicationResolverProtocolV2(Protocol):
    """Resolve request-owned services through the declared Provider alias."""

    def resolve(self, operation: OperationContextV2) -> WorkflowPatternApplicationServicesV2: ...


@dataclass(frozen=True, kw_only=True)
class WorkflowPatternApplicationResolverV2:
    """Application Consumer for one explicitly injected persistence Provider."""

    provider: WorkflowPatternRepositoryFactoryProtocolV2

    def resolve(self, operation: OperationContextV2) -> WorkflowPatternApplicationServicesV2:
        return WorkflowPatternApplicationServicesV2(
            repository=self.provider.build(operation),
        )


def _apply_workflow_pattern_provider_v2(
    context: ContextV2,
    config: Mapping[str, Any],
) -> None:
    if config.get("strategy") != "request-async-session":
        raise ValueError("workflow-pattern provider requires strategy request-async-session")
    _ = context.provide(
        WORKFLOW_PATTERN_PROVIDER_SERVICE_V2,
        SqlWorkflowPatternRepositoryFactoryV2(),
        label="workflow-pattern-provider",
    )


def _apply_workflow_pattern_application_v2(
    context: ContextV2,
    config: Mapping[str, Any],
) -> None:
    if config.get("strategy") != "operation-scoped-provider":
        raise ValueError(
            "workflow-pattern application resolver requires strategy operation-scoped-provider"
        )
    provider = context.require(WORKFLOW_PATTERN_PROVIDER_INJECT_V2)
    if not isinstance(provider, WorkflowPatternRepositoryFactoryProtocolV2):
        raise RuntimeV2Error(
            "invalid_workflow_pattern_provider",
            "workflow-pattern provider inject does not implement the factory contract",
        )
    _ = context.provide(
        WORKFLOW_PATTERN_APPLICATION_SERVICE_V2,
        WorkflowPatternApplicationResolverV2(provider=provider),
        label="workflow-pattern-application",
    )


def workflow_pattern_service_definitions_v2() -> tuple[PluginDefinitionV2, ...]:
    """Return the workflow-pattern persistence Provider and application Consumer."""
    return (
        PluginDefinitionV2(
            module_ref=WORKFLOW_PATTERN_PROVIDER_MODULE_V2,
            contract_digest=generated_contract_digest_v2(WORKFLOW_PATTERN_PROVIDER_MODULE_V2),
            apply=_apply_workflow_pattern_provider_v2,
        ),
        PluginDefinitionV2(
            module_ref=WORKFLOW_PATTERN_APPLICATION_MODULE_V2,
            contract_digest=generated_contract_digest_v2(WORKFLOW_PATTERN_APPLICATION_MODULE_V2),
            apply=_apply_workflow_pattern_application_v2,
        ),
    )


__all__ = [
    "WORKFLOW_PATTERN_APPLICATION_MODULE_V2",
    "WORKFLOW_PATTERN_APPLICATION_SERVICE_V2",
    "WORKFLOW_PATTERN_PROVIDER_INJECT_V2",
    "WORKFLOW_PATTERN_PROVIDER_MODULE_V2",
    "WORKFLOW_PATTERN_PROVIDER_SERVICE_V2",
    "SqlWorkflowPatternRepositoryFactoryV2",
    "WorkflowPatternApplicationResolverProtocolV2",
    "WorkflowPatternApplicationResolverV2",
    "WorkflowPatternApplicationServicesV2",
    "WorkflowPatternRepositoryFactoryProtocolV2",
    "workflow_pattern_service_definitions_v2",
]
