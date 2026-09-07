"""Generation-owned runtime, persistence, and application seams for background tasks."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.adapters.secondary.background_tasks import BackgroundTask, TaskManager
from src.infrastructure.adapters.secondary.common.base_repository import (
    refresh_select_statement,
)
from src.infrastructure.adapters.secondary.persistence.models import UserProject

from .runtime import (
    ContextV2,
    EffectResultV2,
    OperationContextV2,
    PluginDefinitionV2,
    RuntimeV2Error,
    generated_contract_digest_v2,
)

BACKGROUND_TASK_MANAGER_MODULE_V2 = "builtin://memstack/runtime/background-task-manager"
BACKGROUND_TASK_MANAGER_SERVICE_V2 = "service:runtime.background-task-manager"
BACKGROUND_TASK_ACCESS_PROVIDER_MODULE_V2 = (
    "builtin://memstack/persistence/background-task-access-provider"
)
BACKGROUND_TASK_ACCESS_PROVIDER_SERVICE_V2 = "service:persistence.background-task-access-provider"
BACKGROUND_TASK_APPLICATION_MODULE_V2 = "builtin://memstack/application/background-task-services"
BACKGROUND_TASK_APPLICATION_SERVICE_V2 = "service:application.background-task-services"
BACKGROUND_TASK_MANAGER_INJECT_V2 = "manager"
BACKGROUND_TASK_ACCESS_PROVIDER_INJECT_V2 = "provider"
_OPERATION_DB_SESSION_SERVICE_V2 = "service:operation.db-session"

type TaskManagerFactoryV2 = Callable[[], TaskManager]


@dataclass(frozen=True, kw_only=True)
class BackgroundTaskPageV2:
    """Immutable application result returned after identity filtering and limiting."""

    tasks: tuple[Mapping[str, Any], ...]
    total: int


@dataclass(kw_only=True)
class BackgroundTaskManagerRuntimeV2:
    """Process-shared manager retained while at least one generation references it."""

    manager: TaskManager
    _generation_references: int = 0
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def acquire_generation(self) -> None:
        """Start manager lifecycle on the first staged generation."""
        async with self._lock:
            if self._generation_references == 0:
                self.manager.start_cleanup()
            self._generation_references += 1

    async def release_generation(self) -> None:
        """Dispose manager effects only after the final generation is gone."""
        async with self._lock:
            if self._generation_references <= 0:
                raise RuntimeV2Error(
                    "background_task_manager_reference_underflow",
                    "background task manager generation reference count underflow",
                )
            self._generation_references -= 1
            if self._generation_references == 0:
                await self.manager.close()


@runtime_checkable
class BackgroundTaskAccessProtocolV2(Protocol):
    """Operation-owned persistence access used to enforce project membership."""

    async def accessible_project_ids(
        self,
        *,
        user_id: str,
        is_superuser: bool,
    ) -> set[str] | None: ...


@dataclass(frozen=True, kw_only=True)
class SqlBackgroundTaskAccessV2:
    """SQL membership reader bound to exactly one operation session."""

    _session: AsyncSession

    async def accessible_project_ids(
        self,
        *,
        user_id: str,
        is_superuser: bool,
    ) -> set[str] | None:
        if is_superuser:
            return None
        result = await self._session.execute(
            refresh_select_statement(
                select(UserProject.project_id).where(UserProject.user_id == user_id)
            )
        )
        return {str(project_id) for project_id in result.scalars().all()}


@runtime_checkable
class BackgroundTaskAccessFactoryProtocolV2(Protocol):
    """Factory contract hiding the concrete membership persistence adapter."""

    def build(self, operation: OperationContextV2) -> BackgroundTaskAccessProtocolV2: ...


@dataclass(frozen=True, kw_only=True)
class SqlBackgroundTaskAccessFactoryV2:
    """Build membership access from the operation's exact AsyncSession."""

    strategy: str

    def build(self, operation: OperationContextV2) -> BackgroundTaskAccessProtocolV2:
        db = operation.require(_OPERATION_DB_SESSION_SERVICE_V2)
        if not isinstance(db, AsyncSession):
            raise RuntimeV2Error(
                "invalid_operation_db_session",
                "background task services require an AsyncSession operation service",
            )
        return SqlBackgroundTaskAccessV2(_session=db)


@dataclass(frozen=True, kw_only=True)
class BackgroundTaskApplicationServicesV2:
    """Identity-scoped background task operations for one request."""

    manager: TaskManager
    access: BackgroundTaskAccessProtocolV2

    async def list_tasks(
        self,
        *,
        user_id: str,
        is_superuser: bool,
        status: str | None,
        limit: int,
    ) -> BackgroundTaskPageV2:
        project_ids = await self.access.accessible_project_ids(
            user_id=user_id,
            is_superuser=is_superuser,
        )
        visible = [
            task
            for task in self.manager.tasks.values()
            if _task_is_accessible_v2(
                task,
                user_id=user_id,
                project_ids=project_ids,
            )
        ]
        if status:
            visible = [task for task in visible if task.status.value == status]
        visible.sort(key=lambda task: task.created_at, reverse=True)
        return BackgroundTaskPageV2(
            tasks=tuple(task.to_dict() for task in visible[:limit]),
            total=len(visible),
        )


def _task_is_accessible_v2(
    task: BackgroundTask,
    *,
    user_id: str,
    project_ids: set[str] | None,
) -> bool:
    if project_ids is None:
        return True
    if isinstance(task.owner_user_id, str) and task.owner_user_id == user_id:
        return True
    return isinstance(task.project_id, str) and task.project_id in project_ids


@runtime_checkable
class BackgroundTaskApplicationResolverProtocolV2(Protocol):
    """Resolve operation-owned task services through declared aliases only."""

    def resolve(self, operation: OperationContextV2) -> BackgroundTaskApplicationServicesV2: ...


@dataclass(frozen=True, kw_only=True)
class BackgroundTaskApplicationResolverV2:
    """Combine shared runtime state with operation-owned persistence access."""

    manager_runtime: BackgroundTaskManagerRuntimeV2
    access_provider: BackgroundTaskAccessFactoryProtocolV2

    def resolve(self, operation: OperationContextV2) -> BackgroundTaskApplicationServicesV2:
        return BackgroundTaskApplicationServicesV2(
            manager=self.manager_runtime.manager,
            access=self.access_provider.build(operation),
        )


def background_task_manager_definition_v2(
    task_manager_factory: TaskManagerFactoryV2 | None = None,
) -> PluginDefinitionV2:
    """Create one manager shared by every generation staged by the same Loader."""
    manager = (task_manager_factory or TaskManager)()
    runtime = BackgroundTaskManagerRuntimeV2(manager=manager)

    async def apply(context: ContextV2, config: Mapping[str, Any]) -> EffectResultV2:
        if config.get("strategy") != "process-shared":
            raise ValueError("background task manager requires strategy process-shared")
        await runtime.acquire_generation()
        try:
            _ = context.provide(
                BACKGROUND_TASK_MANAGER_SERVICE_V2,
                runtime,
                label="background-task-manager",
            )
        except Exception:
            await runtime.release_generation()
            raise

        async def dispose() -> None:
            await runtime.release_generation()

        return dispose

    return PluginDefinitionV2(
        module_ref=BACKGROUND_TASK_MANAGER_MODULE_V2,
        contract_digest=generated_contract_digest_v2(BACKGROUND_TASK_MANAGER_MODULE_V2),
        apply=apply,
    )


def _apply_background_task_access_provider_v2(
    context: ContextV2,
    config: Mapping[str, Any],
) -> None:
    strategy = config.get("strategy")
    if strategy != "request-async-session":
        raise ValueError("background task access provider requires strategy request-async-session")
    _ = context.provide(
        BACKGROUND_TASK_ACCESS_PROVIDER_SERVICE_V2,
        SqlBackgroundTaskAccessFactoryV2(strategy=strategy),
        label="background-task-access-provider",
    )


def _apply_background_task_application_v2(
    context: ContextV2,
    config: Mapping[str, Any],
) -> None:
    if config.get("strategy") != "operation-scoped-provider":
        raise ValueError(
            "background task application resolver requires strategy operation-scoped-provider"
        )
    manager_runtime = context.require(BACKGROUND_TASK_MANAGER_INJECT_V2)
    if not isinstance(manager_runtime, BackgroundTaskManagerRuntimeV2):
        raise RuntimeV2Error(
            "invalid_background_task_manager",
            "background task manager inject has an invalid implementation",
        )
    access_provider = context.require(BACKGROUND_TASK_ACCESS_PROVIDER_INJECT_V2)
    if not isinstance(access_provider, BackgroundTaskAccessFactoryProtocolV2):
        raise RuntimeV2Error(
            "invalid_background_task_access_provider",
            "background task access provider inject has an invalid implementation",
        )
    _ = context.provide(
        BACKGROUND_TASK_APPLICATION_SERVICE_V2,
        BackgroundTaskApplicationResolverV2(
            manager_runtime=manager_runtime,
            access_provider=access_provider,
        ),
        label="background-task-application",
    )


def background_task_service_definitions_v2(
    task_manager_factory: TaskManagerFactoryV2 | None = None,
) -> tuple[PluginDefinitionV2, ...]:
    """Return the runtime Provider, persistence Provider, and application Consumer."""
    return (
        background_task_manager_definition_v2(task_manager_factory),
        PluginDefinitionV2(
            module_ref=BACKGROUND_TASK_ACCESS_PROVIDER_MODULE_V2,
            contract_digest=generated_contract_digest_v2(BACKGROUND_TASK_ACCESS_PROVIDER_MODULE_V2),
            apply=_apply_background_task_access_provider_v2,
        ),
        PluginDefinitionV2(
            module_ref=BACKGROUND_TASK_APPLICATION_MODULE_V2,
            contract_digest=generated_contract_digest_v2(BACKGROUND_TASK_APPLICATION_MODULE_V2),
            apply=_apply_background_task_application_v2,
        ),
    )


__all__ = [
    "BACKGROUND_TASK_ACCESS_PROVIDER_INJECT_V2",
    "BACKGROUND_TASK_ACCESS_PROVIDER_MODULE_V2",
    "BACKGROUND_TASK_ACCESS_PROVIDER_SERVICE_V2",
    "BACKGROUND_TASK_APPLICATION_MODULE_V2",
    "BACKGROUND_TASK_APPLICATION_SERVICE_V2",
    "BACKGROUND_TASK_MANAGER_INJECT_V2",
    "BACKGROUND_TASK_MANAGER_MODULE_V2",
    "BACKGROUND_TASK_MANAGER_SERVICE_V2",
    "BackgroundTaskAccessFactoryProtocolV2",
    "BackgroundTaskAccessProtocolV2",
    "BackgroundTaskApplicationResolverProtocolV2",
    "BackgroundTaskApplicationResolverV2",
    "BackgroundTaskApplicationServicesV2",
    "BackgroundTaskManagerRuntimeV2",
    "BackgroundTaskPageV2",
    "SqlBackgroundTaskAccessFactoryV2",
    "SqlBackgroundTaskAccessV2",
    "TaskManagerFactoryV2",
    "background_task_manager_definition_v2",
    "background_task_service_definitions_v2",
]
