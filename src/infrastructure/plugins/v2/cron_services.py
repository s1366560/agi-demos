"""Generation-owned runtime, persistence, and application seams for Cron operations."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.services.automation_command_service import AutomationCommandService
from src.application.services.cron_service import CronJobService
from src.domain.model.cron.cron_job import CronJob
from src.infrastructure.adapters.secondary.common.base_repository import (
    refresh_select_statement,
)
from src.infrastructure.adapters.secondary.persistence.models import UserProject
from src.infrastructure.adapters.secondary.persistence.sql_cron_automation_command_repository import (
    SqlCronAutomationCommandRepository,
)
from src.infrastructure.adapters.secondary.persistence.sql_cron_job_repository import (
    SqlCronJobRepository,
    SqlCronJobRunRepository,
)
from src.infrastructure.scheduler import scheduler_service

from .project_tenant_services import (
    ProjectTenantApplicationResolverProtocolV2,
    ProjectTenantServicesV2,
)
from .runtime import (
    ContextV2,
    EffectResultV2,
    OperationContextV2,
    PluginDefinitionV2,
    RuntimeV2Error,
    generated_contract_digest_v2,
)

logger = logging.getLogger(__name__)

CRON_SCHEDULER_GATEWAY_MODULE_V2 = "builtin://memstack/runtime/cron-scheduler-gateway"
CRON_SCHEDULER_GATEWAY_SERVICE_V2 = "service:runtime.cron-scheduler-gateway"
CRON_PERSISTENCE_PROVIDER_MODULE_V2 = "builtin://memstack/persistence/cron-provider"
CRON_PERSISTENCE_PROVIDER_SERVICE_V2 = "service:persistence.cron-provider"
CRON_APPLICATION_MODULE_V2 = "builtin://memstack/application/cron-services"
CRON_APPLICATION_SERVICE_V2 = "service:application.cron-services"
CRON_PROVIDER_INJECT_V2 = "provider"
CRON_PROJECTS_INJECT_V2 = "projects"
CRON_SCHEDULER_INJECT_V2 = "scheduler"
_OPERATION_DB_SESSION_SERVICE_V2 = "service:operation.db-session"

type CronSchedulerStartV2 = Callable[[], Awaitable[object]]
type CronSchedulerSyncV2 = Callable[[], Awaitable[None]]
type CronSchedulerStopV2 = Callable[[], Awaitable[None]]


class CronServiceErrorV2(Exception):
    """Base class for typed generation-owned Cron failures."""


class CronProjectAccessDeniedV2(CronServiceErrorV2):
    """The authenticated user is not a member of the requested project."""


@runtime_checkable
class CronSchedulerGatewayProtocolV2(Protocol):
    """Generation-visible schedule synchronization boundary."""

    async def register(
        self,
        *,
        job_id: str,
        schedule_type: str,
        schedule_config: dict[str, Any],
        timezone: str,
    ) -> None: ...

    async def unregister(self, job_id: str) -> None: ...


@dataclass(frozen=True, kw_only=True)
class BuiltinCronSchedulerGatewayV2:
    """Bridge the current scheduler runtime through an explicit V2 service."""

    async def register(
        self,
        *,
        job_id: str,
        schedule_type: str,
        schedule_config: dict[str, Any],
        timezone: str,
    ) -> None:
        await scheduler_service.register_job(
            job_id=job_id,
            schedule_type=schedule_type,
            schedule_config=schedule_config,
            timezone=timezone,
        )

    async def unregister(self, job_id: str) -> None:
        await scheduler_service.unregister_job(job_id)


@dataclass(kw_only=True)
class _CronSchedulerRuntimeManagerV2:
    """Reference-count the process scheduler across overlapping generations."""

    start: CronSchedulerStartV2
    sync: CronSchedulerSyncV2
    stop: CronSchedulerStopV2
    _generation_references: int = 0
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def acquire_generation(self) -> None:
        """Start and hydrate only for the first staged generation."""
        async with self._lock:
            if self._generation_references == 0:
                started = False
                try:
                    _ = await self.start()
                    started = True
                    await self.sync()
                except BaseException:
                    if started:
                        try:
                            await self.stop()
                        except Exception:
                            logger.exception("Failed to clean up Cron scheduler candidate")
                    raise
            self._generation_references += 1

    async def release_generation(self) -> None:
        """Stop only after every active or draining generation releases its effect."""
        async with self._lock:
            if self._generation_references <= 0:
                raise RuntimeV2Error(
                    "cron_scheduler_reference_underflow",
                    "cron scheduler generation reference count underflow",
                )
            self._generation_references -= 1
            if self._generation_references == 0:
                await self.stop()


@runtime_checkable
class CronProjectAccessProtocolV2(Protocol):
    """Operation-owned project membership boundary."""

    async def require_project_access(self, *, project_id: str, user_id: str) -> None: ...


@dataclass(frozen=True, kw_only=True)
class SqlCronProjectAccessV2:
    """Read project membership from exactly one operation session."""

    _session: AsyncSession

    async def require_project_access(self, *, project_id: str, user_id: str) -> None:
        result = await self._session.execute(
            refresh_select_statement(
                select(UserProject.id).where(
                    UserProject.user_id == user_id,
                    UserProject.project_id == project_id,
                )
            )
        )
        if result.scalar_one_or_none() is None:
            raise CronProjectAccessDeniedV2


@dataclass(frozen=True, kw_only=True)
class CronPersistenceServicesV2:
    """Persistence-backed Cron services owned by one operation."""

    cron_jobs: CronJobService
    commands: AutomationCommandService
    access: CronProjectAccessProtocolV2


@runtime_checkable
class CronPersistenceFactoryProtocolV2(Protocol):
    """Factory contract hiding concrete Cron repositories."""

    def build(self, operation: OperationContextV2) -> CronPersistenceServicesV2: ...


@dataclass(frozen=True, kw_only=True)
class SqlCronPersistenceFactoryV2:
    """Construct every Cron persistence adapter from the operation session."""

    strategy: str

    def build(self, operation: OperationContextV2) -> CronPersistenceServicesV2:
        db = operation.require(_OPERATION_DB_SESSION_SERVICE_V2)
        if not isinstance(db, AsyncSession):
            raise RuntimeV2Error(
                "invalid_operation_db_session",
                "cron services require an AsyncSession operation service",
            )
        return CronPersistenceServicesV2(
            cron_jobs=CronJobService(
                cron_job_repo=SqlCronJobRepository(db),
                cron_job_run_repo=SqlCronJobRunRepository(db),
            ),
            commands=AutomationCommandService(SqlCronAutomationCommandRepository(db)),
            access=SqlCronProjectAccessV2(_session=db),
        )


@dataclass(frozen=True, kw_only=True)
class CronApplicationServicesV2:
    """Complete operation-owned Cron application service set."""

    cron_jobs: CronJobService
    commands: AutomationCommandService
    access: CronProjectAccessProtocolV2
    projects: ProjectTenantServicesV2
    scheduler: CronSchedulerGatewayProtocolV2

    async def require_project_access(self, *, project_id: str, user_id: str) -> None:
        await self.access.require_project_access(project_id=project_id, user_id=user_id)


@runtime_checkable
class CronApplicationResolverProtocolV2(Protocol):
    """Resolve Cron services through declared aliases only."""

    def resolve(self, operation: OperationContextV2) -> CronApplicationServicesV2: ...


@dataclass(frozen=True, kw_only=True)
class CronApplicationResolverV2:
    """Combine persistence, project, and scheduler seams for one operation."""

    provider: CronPersistenceFactoryProtocolV2
    projects: ProjectTenantApplicationResolverProtocolV2
    scheduler: CronSchedulerGatewayProtocolV2

    def resolve(self, operation: OperationContextV2) -> CronApplicationServicesV2:
        persistence = self.provider.build(operation)
        return CronApplicationServicesV2(
            cron_jobs=persistence.cron_jobs,
            commands=persistence.commands,
            access=persistence.access,
            projects=self.projects.resolve(operation),
            scheduler=self.scheduler,
        )


async def sync_cron_schedule_v2(
    services: CronApplicationServicesV2,
    *,
    job: CronJob,
    enabled: bool,
) -> None:
    """Best-effort synchronization through the generation-owned scheduler seam."""
    try:
        if enabled:
            await services.scheduler.register(
                job_id=job.id,
                schedule_type=job.schedule.kind.value,
                schedule_config=job.schedule.config,
                timezone=job.timezone,
            )
        else:
            await services.scheduler.unregister(job.id)
    except Exception:
        logger.debug("Scheduler unavailable while synchronizing Cron job %s", job.id)


async def remove_cron_schedule_v2(
    services: CronApplicationServicesV2,
    *,
    job_id: str,
) -> None:
    """Best-effort schedule removal through the generation-owned scheduler seam."""
    try:
        await services.scheduler.unregister(job_id)
    except Exception:
        logger.debug("Scheduler unavailable while removing Cron job %s", job_id)


def cron_scheduler_gateway_definition_v2() -> PluginDefinitionV2:
    """Bind scheduler startup, hydration, and teardown to V2 generation effects."""
    runtime = _CronSchedulerRuntimeManagerV2(
        start=scheduler_service.start_scheduler,
        sync=scheduler_service.sync_all_jobs,
        stop=scheduler_service.stop_scheduler,
    )

    async def apply(context: ContextV2, config: Mapping[str, Any]) -> EffectResultV2:
        if config.get("strategy") != "builtin-scheduler-bridge":
            raise ValueError("cron scheduler gateway requires strategy builtin-scheduler-bridge")
        await runtime.acquire_generation()
        try:
            _ = context.provide(
                CRON_SCHEDULER_GATEWAY_SERVICE_V2,
                BuiltinCronSchedulerGatewayV2(),
                label="cron-scheduler-gateway",
            )
        except Exception:
            await runtime.release_generation()
            raise

        async def dispose() -> None:
            await runtime.release_generation()

        return dispose

    return PluginDefinitionV2(
        module_ref=CRON_SCHEDULER_GATEWAY_MODULE_V2,
        contract_digest=generated_contract_digest_v2(CRON_SCHEDULER_GATEWAY_MODULE_V2),
        apply=apply,
    )


def _apply_cron_persistence_provider_v2(
    context: ContextV2,
    config: Mapping[str, Any],
) -> None:
    if config.get("strategy") != "request-async-session":
        raise ValueError("cron persistence provider requires strategy request-async-session")
    _ = context.provide(
        CRON_PERSISTENCE_PROVIDER_SERVICE_V2,
        SqlCronPersistenceFactoryV2(strategy="request-async-session"),
        label="cron-persistence-provider",
    )


def _apply_cron_application_v2(
    context: ContextV2,
    config: Mapping[str, Any],
) -> None:
    if config.get("strategy") != "operation-scoped-provider":
        raise ValueError("cron application resolver requires strategy operation-scoped-provider")
    provider = context.require(CRON_PROVIDER_INJECT_V2)
    projects = context.require(CRON_PROJECTS_INJECT_V2)
    scheduler = context.require(CRON_SCHEDULER_INJECT_V2)
    if not isinstance(provider, CronPersistenceFactoryProtocolV2):
        raise RuntimeV2Error(
            "invalid_cron_persistence_provider",
            "cron provider inject does not implement the factory contract",
        )
    if not isinstance(projects, ProjectTenantApplicationResolverProtocolV2):
        raise RuntimeV2Error(
            "invalid_cron_project_services",
            "cron project inject does not implement the resolver contract",
        )
    if not isinstance(scheduler, CronSchedulerGatewayProtocolV2):
        raise RuntimeV2Error(
            "invalid_cron_scheduler_gateway",
            "cron scheduler inject does not implement the gateway contract",
        )
    _ = context.provide(
        CRON_APPLICATION_SERVICE_V2,
        CronApplicationResolverV2(
            provider=provider,
            projects=projects,
            scheduler=scheduler,
        ),
        label="cron-application",
    )


def cron_service_definitions_v2() -> tuple[PluginDefinitionV2, ...]:
    """Return Cron runtime, persistence Provider, and application Consumer definitions."""
    return (
        cron_scheduler_gateway_definition_v2(),
        PluginDefinitionV2(
            module_ref=CRON_PERSISTENCE_PROVIDER_MODULE_V2,
            contract_digest=generated_contract_digest_v2(CRON_PERSISTENCE_PROVIDER_MODULE_V2),
            apply=_apply_cron_persistence_provider_v2,
        ),
        PluginDefinitionV2(
            module_ref=CRON_APPLICATION_MODULE_V2,
            contract_digest=generated_contract_digest_v2(CRON_APPLICATION_MODULE_V2),
            apply=_apply_cron_application_v2,
        ),
    )


__all__ = [
    "CRON_APPLICATION_MODULE_V2",
    "CRON_APPLICATION_SERVICE_V2",
    "CRON_PERSISTENCE_PROVIDER_MODULE_V2",
    "CRON_PERSISTENCE_PROVIDER_SERVICE_V2",
    "CRON_PROJECTS_INJECT_V2",
    "CRON_PROVIDER_INJECT_V2",
    "CRON_SCHEDULER_GATEWAY_MODULE_V2",
    "CRON_SCHEDULER_GATEWAY_SERVICE_V2",
    "CRON_SCHEDULER_INJECT_V2",
    "BuiltinCronSchedulerGatewayV2",
    "CronApplicationResolverProtocolV2",
    "CronApplicationResolverV2",
    "CronApplicationServicesV2",
    "CronPersistenceFactoryProtocolV2",
    "CronPersistenceServicesV2",
    "CronProjectAccessDeniedV2",
    "CronProjectAccessProtocolV2",
    "CronSchedulerGatewayProtocolV2",
    "CronServiceErrorV2",
    "SqlCronPersistenceFactoryV2",
    "SqlCronProjectAccessV2",
    "cron_scheduler_gateway_definition_v2",
    "cron_service_definitions_v2",
    "remove_cron_schedule_v2",
    "sync_cron_schedule_v2",
]
