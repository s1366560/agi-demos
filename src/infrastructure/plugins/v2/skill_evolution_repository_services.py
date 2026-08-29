"""Generation-owned persistence seam for SkillEvolution state."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.agent.plugins.skill_evolution.models import (
    SkillEvolutionJob,
    SkillEvolutionSession,
)
from src.infrastructure.agent.plugins.skill_evolution.repository import (
    SkillEvolutionRepository,
)

from .runtime import (
    ContextV2,
    OperationContextV2,
    PluginDefinitionV2,
    RuntimeV2Error,
    generated_contract_digest_v2,
)

SKILL_EVOLUTION_REPOSITORY_PROVIDER_MODULE_V2 = (
    "builtin://memstack/persistence/skill-evolution-repository-provider"
)
SKILL_EVOLUTION_REPOSITORY_PROVIDER_SERVICE_V2 = (
    "service:persistence.skill-evolution-repository-provider"
)
SKILL_EVOLUTION_REPOSITORY_APPLICATION_MODULE_V2 = (
    "builtin://memstack/application/skill-evolution-repository"
)
SKILL_EVOLUTION_REPOSITORY_APPLICATION_SERVICE_V2 = "service:application.skill-evolution-repository"
SKILL_EVOLUTION_REPOSITORY_PROVIDER_INJECT_V2 = "repository_provider"
_OPERATION_DB_SESSION_SERVICE_V2 = "service:operation.db-session"


@runtime_checkable
class SkillEvolutionRepositoryProtocolV2(Protocol):
    """Read and review persistence exposed to SkillEvolution HTTP Consumers."""

    async def get_job(self, job_id: str) -> SkillEvolutionJob | None: ...

    async def update_job_status(
        self,
        job_id: str,
        *,
        status: str,
        skill_version_id: str | None = None,
    ) -> None: ...

    async def list_jobs(
        self,
        *,
        tenant_id: str,
        status: str | None = None,
        skill_name: str | None = None,
        project_id: str | None = None,
        filter_project_id: bool = False,
        project_ids: set[str] | None = None,
        limit: int = 50,
    ) -> list[SkillEvolutionJob]: ...

    async def count_sessions_by_skill(
        self,
        *,
        tenant_id: str,
        skill_name: str,
        project_id: str | None = None,
        filter_project_id: bool = False,
    ) -> int: ...

    async def get_overview_stats(
        self,
        *,
        tenant_id: str,
        project_ids: set[str] | None = None,
    ) -> dict[str, object]: ...

    async def get_skill_session_summaries(
        self,
        *,
        tenant_id: str,
        project_id: str | None = None,
        filter_project_id: bool = False,
        project_ids: set[str] | None = None,
        limit: int = 50,
    ) -> list[dict[str, object]]: ...

    async def list_recent_sessions(
        self,
        *,
        tenant_id: str,
        skill_name: str | None = None,
        project_id: str | None = None,
        filter_project_id: bool = False,
        project_ids: set[str] | None = None,
        limit: int = 50,
    ) -> list[SkillEvolutionSession]: ...


@runtime_checkable
class SkillEvolutionRepositoryProviderProtocolV2(Protocol):
    """Build SkillEvolution persistence from one operation boundary."""

    def build(self, operation: OperationContextV2) -> SkillEvolutionRepositoryProtocolV2: ...


@dataclass(frozen=True, kw_only=True)
class SqlSkillEvolutionRepositoryProviderV2:
    """Construct SQL SkillEvolution repositories from request-owned sessions."""

    strategy: str

    def build(self, operation: OperationContextV2) -> SkillEvolutionRepositoryProtocolV2:
        db = operation.require(_OPERATION_DB_SESSION_SERVICE_V2)
        if not isinstance(db, AsyncSession):
            raise RuntimeV2Error(
                "invalid_operation_db_session",
                "SkillEvolution repository Provider requires an AsyncSession operation service",
            )
        return SkillEvolutionRepository(db)


@dataclass(frozen=True, kw_only=True)
class SkillEvolutionRepositoryApplicationServicesV2:
    """Operation-owned SkillEvolution persistence for application Consumers."""

    repository: SkillEvolutionRepositoryProtocolV2


@runtime_checkable
class SkillEvolutionRepositoryApplicationResolverProtocolV2(Protocol):
    """Resolve SkillEvolution persistence through the declared Provider alias."""

    def resolve(
        self,
        operation: OperationContextV2,
    ) -> SkillEvolutionRepositoryApplicationServicesV2: ...


@dataclass(frozen=True, kw_only=True)
class SkillEvolutionRepositoryApplicationResolverV2:
    """Bind the Profile-selected repository Provider to one operation."""

    repository_provider: SkillEvolutionRepositoryProviderProtocolV2

    def resolve(
        self,
        operation: OperationContextV2,
    ) -> SkillEvolutionRepositoryApplicationServicesV2:
        return SkillEvolutionRepositoryApplicationServicesV2(
            repository=self.repository_provider.build(operation),
        )


def _apply_skill_evolution_repository_provider_v2(
    context: ContextV2,
    config: Mapping[str, Any],
) -> None:
    strategy = config.get("strategy")
    if strategy != "request-async-session":
        raise ValueError(
            "SkillEvolution repository Provider requires strategy request-async-session"
        )
    _ = context.provide(
        SKILL_EVOLUTION_REPOSITORY_PROVIDER_SERVICE_V2,
        SqlSkillEvolutionRepositoryProviderV2(strategy=strategy),
        label="skill-evolution-repository-provider",
    )


def _apply_skill_evolution_repository_application_v2(
    context: ContextV2,
    config: Mapping[str, Any],
) -> None:
    if config.get("strategy") != "operation-scoped-provider":
        raise ValueError(
            "SkillEvolution repository application resolver requires operation-scoped-provider"
        )
    repository_provider = context.require(SKILL_EVOLUTION_REPOSITORY_PROVIDER_INJECT_V2)
    if not isinstance(repository_provider, SkillEvolutionRepositoryProviderProtocolV2):
        raise RuntimeV2Error(
            "invalid_skill_evolution_repository_provider",
            "SkillEvolution repository Provider inject has an invalid implementation",
        )
    _ = context.provide(
        SKILL_EVOLUTION_REPOSITORY_APPLICATION_SERVICE_V2,
        SkillEvolutionRepositoryApplicationResolverV2(
            repository_provider=repository_provider,
        ),
        label="skill-evolution-repository-application",
    )


def skill_evolution_repository_service_definitions_v2() -> tuple[PluginDefinitionV2, ...]:
    """Return the SkillEvolution repository Provider and application Consumer."""
    return (
        PluginDefinitionV2(
            module_ref=SKILL_EVOLUTION_REPOSITORY_PROVIDER_MODULE_V2,
            contract_digest=generated_contract_digest_v2(
                SKILL_EVOLUTION_REPOSITORY_PROVIDER_MODULE_V2
            ),
            apply=_apply_skill_evolution_repository_provider_v2,
        ),
        PluginDefinitionV2(
            module_ref=SKILL_EVOLUTION_REPOSITORY_APPLICATION_MODULE_V2,
            contract_digest=generated_contract_digest_v2(
                SKILL_EVOLUTION_REPOSITORY_APPLICATION_MODULE_V2
            ),
            apply=_apply_skill_evolution_repository_application_v2,
        ),
    )


__all__ = [
    "SKILL_EVOLUTION_REPOSITORY_APPLICATION_MODULE_V2",
    "SKILL_EVOLUTION_REPOSITORY_APPLICATION_SERVICE_V2",
    "SKILL_EVOLUTION_REPOSITORY_PROVIDER_INJECT_V2",
    "SKILL_EVOLUTION_REPOSITORY_PROVIDER_MODULE_V2",
    "SKILL_EVOLUTION_REPOSITORY_PROVIDER_SERVICE_V2",
    "SkillEvolutionRepositoryApplicationResolverProtocolV2",
    "SkillEvolutionRepositoryApplicationResolverV2",
    "SkillEvolutionRepositoryApplicationServicesV2",
    "SkillEvolutionRepositoryProtocolV2",
    "SkillEvolutionRepositoryProviderProtocolV2",
    "SqlSkillEvolutionRepositoryProviderV2",
    "skill_evolution_repository_service_definitions_v2",
]
