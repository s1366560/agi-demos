"""Generation-owned persistence and application seams for durable task logs."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from sqlalchemy.ext.asyncio import AsyncSession

from src.application.use_cases.task import GetTaskUseCase, UpdateTaskUseCase
from src.domain.ports.repositories.task_repository import TaskRepository
from src.infrastructure.adapters.secondary.persistence.sql_task_repository import (
    SqlTaskRepository,
)

from .runtime import (
    ContextV2,
    OperationContextV2,
    PluginDefinitionV2,
    RuntimeV2Error,
    generated_contract_digest_v2,
)

TASK_LOG_REPOSITORY_PROVIDER_MODULE_V2 = (
    "builtin://memstack/persistence/task-log-repository-provider"
)
TASK_LOG_REPOSITORY_PROVIDER_SERVICE_V2 = "service:persistence.task-log-repository-provider"
TASK_LOG_APPLICATION_MODULE_V2 = "builtin://memstack/application/task-log-services"
TASK_LOG_APPLICATION_SERVICE_V2 = "service:application.task-log-services"
TASK_LOG_REPOSITORY_INJECT_V2 = "repository_provider"
_OPERATION_DB_SESSION_SERVICE_V2 = "service:operation.db-session"


@runtime_checkable
class TaskLogRepositoryFactoryProtocolV2(Protocol):
    """Build a repository from the current operation boundary."""

    def build(self, operation: OperationContextV2) -> TaskRepository: ...


@dataclass(frozen=True, kw_only=True)
class SqlTaskLogRepositoryFactoryV2:
    """Construct a SQL repository from the request's exact session."""

    strategy: str

    def build(self, operation: OperationContextV2) -> TaskRepository:
        db = operation.require(_OPERATION_DB_SESSION_SERVICE_V2)
        if not isinstance(db, AsyncSession):
            raise RuntimeV2Error(
                "invalid_operation_db_session",
                "task log services require an AsyncSession operation service",
            )
        return SqlTaskRepository(db)


@dataclass(frozen=True, kw_only=True)
class TaskLogApplicationServicesV2:
    """Operation-owned task-log use cases."""

    get_task: GetTaskUseCase
    update_task: UpdateTaskUseCase


@runtime_checkable
class TaskLogApplicationResolverProtocolV2(Protocol):
    """Resolve task-log use cases for one operation."""

    def resolve(self, operation: OperationContextV2) -> TaskLogApplicationServicesV2: ...


@dataclass(frozen=True, kw_only=True)
class TaskLogApplicationResolverV2:
    """Bind a declared repository Provider to operation-owned use cases."""

    repository_provider: TaskLogRepositoryFactoryProtocolV2

    def resolve(self, operation: OperationContextV2) -> TaskLogApplicationServicesV2:
        repository = self.repository_provider.build(operation)
        return TaskLogApplicationServicesV2(
            get_task=GetTaskUseCase(repository),
            update_task=UpdateTaskUseCase(repository),
        )


def _apply_task_log_repository_provider_v2(
    context: ContextV2,
    config: Mapping[str, Any],
) -> None:
    strategy = config.get("strategy")
    if strategy != "request-async-session":
        raise ValueError("task log repository provider requires strategy request-async-session")
    _ = context.provide(
        TASK_LOG_REPOSITORY_PROVIDER_SERVICE_V2,
        SqlTaskLogRepositoryFactoryV2(strategy=strategy),
        label="task-log-repository-provider",
    )


def _apply_task_log_application_v2(
    context: ContextV2,
    config: Mapping[str, Any],
) -> None:
    if config.get("strategy") != "operation-scoped-provider":
        raise ValueError(
            "task log application resolver requires strategy operation-scoped-provider"
        )
    repository_provider = context.require(TASK_LOG_REPOSITORY_INJECT_V2)
    if not isinstance(repository_provider, TaskLogRepositoryFactoryProtocolV2):
        raise RuntimeV2Error(
            "invalid_task_log_repository_provider",
            "task log repository provider inject has an invalid implementation",
        )
    _ = context.provide(
        TASK_LOG_APPLICATION_SERVICE_V2,
        TaskLogApplicationResolverV2(repository_provider=repository_provider),
        label="task-log-application",
    )


def task_log_service_definitions_v2() -> tuple[PluginDefinitionV2, ...]:
    """Return the persistence Provider and its explicit application Consumer."""
    return (
        PluginDefinitionV2(
            module_ref=TASK_LOG_REPOSITORY_PROVIDER_MODULE_V2,
            contract_digest=generated_contract_digest_v2(TASK_LOG_REPOSITORY_PROVIDER_MODULE_V2),
            apply=_apply_task_log_repository_provider_v2,
        ),
        PluginDefinitionV2(
            module_ref=TASK_LOG_APPLICATION_MODULE_V2,
            contract_digest=generated_contract_digest_v2(TASK_LOG_APPLICATION_MODULE_V2),
            apply=_apply_task_log_application_v2,
        ),
    )


__all__ = [
    "TASK_LOG_APPLICATION_MODULE_V2",
    "TASK_LOG_APPLICATION_SERVICE_V2",
    "TASK_LOG_REPOSITORY_INJECT_V2",
    "TASK_LOG_REPOSITORY_PROVIDER_MODULE_V2",
    "TASK_LOG_REPOSITORY_PROVIDER_SERVICE_V2",
    "SqlTaskLogRepositoryFactoryV2",
    "TaskLogApplicationResolverProtocolV2",
    "TaskLogApplicationResolverV2",
    "TaskLogApplicationServicesV2",
    "TaskLogRepositoryFactoryProtocolV2",
    "task_log_service_definitions_v2",
]
