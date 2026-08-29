"""Generation-owned persistence seam for Skill repositories."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.ports.repositories.skill_repository import SkillRepositoryPort
from src.infrastructure.adapters.secondary.persistence.sql_skill_repository import (
    SqlSkillRepository,
)

from .runtime import (
    ContextV2,
    OperationContextV2,
    PluginDefinitionV2,
    RuntimeV2Error,
    generated_contract_digest_v2,
)

SKILL_REPOSITORY_PROVIDER_MODULE_V2 = "builtin://memstack/persistence/skill-repository-provider"
SKILL_REPOSITORY_PROVIDER_SERVICE_V2 = "service:persistence.skill-repository-provider"
SKILL_REPOSITORY_APPLICATION_MODULE_V2 = "builtin://memstack/application/skill-repository"
SKILL_REPOSITORY_APPLICATION_SERVICE_V2 = "service:application.skill-repository"
SKILL_REPOSITORY_PROVIDER_INJECT_V2 = "repository_provider"
_OPERATION_DB_SESSION_SERVICE_V2 = "service:operation.db-session"


@runtime_checkable
class SkillRepositoryProviderProtocolV2(Protocol):
    """Build a Skill repository from the current operation boundary."""

    def build(self, operation: OperationContextV2) -> SkillRepositoryPort: ...


@dataclass(frozen=True, kw_only=True)
class SqlSkillRepositoryProviderV2:
    """Construct SQL Skill repositories from request-owned sessions."""

    strategy: str

    def build(self, operation: OperationContextV2) -> SkillRepositoryPort:
        db = operation.require(_OPERATION_DB_SESSION_SERVICE_V2)
        if not isinstance(db, AsyncSession):
            raise RuntimeV2Error(
                "invalid_operation_db_session",
                "Skill repository Provider requires an AsyncSession operation service",
            )
        return SqlSkillRepository(db)


@dataclass(frozen=True, kw_only=True)
class SkillRepositoryApplicationServicesV2:
    """Operation-owned persistence seam exposed to Skill HTTP handlers."""

    repository: SkillRepositoryPort


@runtime_checkable
class SkillRepositoryApplicationResolverProtocolV2(Protocol):
    """Resolve one Skill repository from the declared Provider alias."""

    def resolve(self, operation: OperationContextV2) -> SkillRepositoryApplicationServicesV2: ...


@dataclass(frozen=True, kw_only=True)
class SkillRepositoryApplicationResolverV2:
    """Bind the Profile-selected repository Provider to one operation."""

    repository_provider: SkillRepositoryProviderProtocolV2

    def resolve(self, operation: OperationContextV2) -> SkillRepositoryApplicationServicesV2:
        return SkillRepositoryApplicationServicesV2(
            repository=self.repository_provider.build(operation),
        )


def _apply_skill_repository_provider_v2(
    context: ContextV2,
    config: Mapping[str, Any],
) -> None:
    strategy = config.get("strategy")
    if strategy != "request-async-session":
        raise ValueError("Skill repository Provider requires strategy request-async-session")
    _ = context.provide(
        SKILL_REPOSITORY_PROVIDER_SERVICE_V2,
        SqlSkillRepositoryProviderV2(strategy=strategy),
        label="skill-repository-provider",
    )


def _apply_skill_repository_application_v2(
    context: ContextV2,
    config: Mapping[str, Any],
) -> None:
    if config.get("strategy") != "operation-scoped-provider":
        raise ValueError(
            "Skill repository application resolver requires strategy operation-scoped-provider"
        )
    repository_provider = context.require(SKILL_REPOSITORY_PROVIDER_INJECT_V2)
    if not isinstance(repository_provider, SkillRepositoryProviderProtocolV2):
        raise RuntimeV2Error(
            "invalid_skill_repository_provider",
            "Skill repository Provider inject has an invalid implementation",
        )
    _ = context.provide(
        SKILL_REPOSITORY_APPLICATION_SERVICE_V2,
        SkillRepositoryApplicationResolverV2(repository_provider=repository_provider),
        label="skill-repository-application",
    )


def skill_repository_service_definitions_v2() -> tuple[PluginDefinitionV2, ...]:
    """Return the Skill repository Provider and application Consumer."""
    return (
        PluginDefinitionV2(
            module_ref=SKILL_REPOSITORY_PROVIDER_MODULE_V2,
            contract_digest=generated_contract_digest_v2(SKILL_REPOSITORY_PROVIDER_MODULE_V2),
            apply=_apply_skill_repository_provider_v2,
        ),
        PluginDefinitionV2(
            module_ref=SKILL_REPOSITORY_APPLICATION_MODULE_V2,
            contract_digest=generated_contract_digest_v2(SKILL_REPOSITORY_APPLICATION_MODULE_V2),
            apply=_apply_skill_repository_application_v2,
        ),
    )


__all__ = [
    "SKILL_REPOSITORY_APPLICATION_MODULE_V2",
    "SKILL_REPOSITORY_APPLICATION_SERVICE_V2",
    "SKILL_REPOSITORY_PROVIDER_INJECT_V2",
    "SKILL_REPOSITORY_PROVIDER_MODULE_V2",
    "SKILL_REPOSITORY_PROVIDER_SERVICE_V2",
    "SkillRepositoryApplicationResolverProtocolV2",
    "SkillRepositoryApplicationResolverV2",
    "SkillRepositoryApplicationServicesV2",
    "SkillRepositoryProviderProtocolV2",
    "SqlSkillRepositoryProviderV2",
    "skill_repository_service_definitions_v2",
]
