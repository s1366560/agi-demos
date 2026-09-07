# pyright: reportImportCycles=false, reportUnnecessaryIsInstance=false
"""Composite FastAPI authority for generation-owned SkillEvolution state."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from uuid import uuid4

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.domain.ports.repositories.skill_repository import SkillRepositoryPort
from src.domain.ports.repositories.skill_version_repository import SkillVersionRepositoryPort
from src.infrastructure.adapters.secondary.persistence.models import User
from src.infrastructure.plugins.v2.boundary import (
    OPERATION_DB_SESSION_SERVICE_V2,
    OPERATION_IDENTITY_SERVICE_V2,
    OPERATION_METADATA_SERVICE_V2,
    current_generation_v2,
)
from src.infrastructure.plugins.v2.plugin_config_services import (
    PLUGIN_CONFIG_APPLICATION_SERVICE_V2,
    PluginConfigApplicationResolverProtocolV2,
    PluginConfigRepositoryProtocolV2,
)
from src.infrastructure.plugins.v2.runtime import OperationContextV2, RuntimeV2Error
from src.infrastructure.plugins.v2.skill_evolution_repository_services import (
    SKILL_EVOLUTION_REPOSITORY_APPLICATION_SERVICE_V2,
    SkillEvolutionRepositoryApplicationResolverProtocolV2,
    SkillEvolutionRepositoryProtocolV2,
)
from src.infrastructure.plugins.v2.skill_repository_services import (
    SKILL_REPOSITORY_APPLICATION_SERVICE_V2,
    SkillRepositoryApplicationResolverProtocolV2,
)


@dataclass(frozen=True, kw_only=True)
class SkillEvolutionHttpApplicationAuthorityV2:
    """Request-owned repositories resolved inside one disposable operation."""

    operation: OperationContextV2
    db: AsyncSession
    evolution_repository: SkillEvolutionRepositoryProtocolV2
    skill_repository: SkillRepositoryPort
    skill_version_repository: SkillVersionRepositoryPort
    plugin_config_repository: PluginConfigRepositoryProtocolV2


@asynccontextmanager
async def skill_evolution_http_application_authority_v2(
    *,
    request: Request,
    tenant_id: str,
    current_user: User,
    db: AsyncSession,
) -> AsyncIterator[SkillEvolutionHttpApplicationAuthorityV2]:
    """Yield all SkillEvolution repositories from the request's pinned generation."""
    operation = OperationContextV2(
        generation=current_generation_v2(),
        operation_id=f"http-skill-evolution:{uuid4()}",
        scope=ScopeV2(kind=ScopeKindV2.TENANT, tenant_id=tenant_id),
    )
    async with operation:
        _ = operation.provide(OPERATION_DB_SESSION_SERVICE_V2, db)
        _ = operation.provide(
            OPERATION_IDENTITY_SERVICE_V2,
            {"tenant_id": tenant_id, "user_id": str(current_user.id)},
        )
        _ = operation.provide(
            OPERATION_METADATA_SERVICE_V2,
            {"kind": "http-authority", "method": request.method, "path": request.url.path},
        )

        evolution_resolver = operation.require(SKILL_EVOLUTION_REPOSITORY_APPLICATION_SERVICE_V2)
        if not isinstance(
            evolution_resolver,
            SkillEvolutionRepositoryApplicationResolverProtocolV2,
        ):
            raise RuntimeV2Error(
                "invalid_skill_evolution_repository_application_resolver",
                "SkillEvolution repository application service has an invalid resolver",
            )
        evolution_repository = evolution_resolver.resolve(operation).repository
        if not isinstance(evolution_repository, SkillEvolutionRepositoryProtocolV2):
            raise RuntimeV2Error(
                "invalid_skill_evolution_repository",
                "SkillEvolution repository Provider returned an invalid repository",
            )

        skill_resolver = operation.require(SKILL_REPOSITORY_APPLICATION_SERVICE_V2)
        if not isinstance(skill_resolver, SkillRepositoryApplicationResolverProtocolV2):
            raise RuntimeV2Error(
                "invalid_skill_repository_application_resolver",
                "Skill repository application service has an invalid resolver",
            )
        skill_services = skill_resolver.resolve(operation)
        if not isinstance(skill_services.repository, SkillRepositoryPort):
            raise RuntimeV2Error(
                "invalid_skill_repository",
                "Skill repository Provider returned an invalid repository",
            )
        if not isinstance(skill_services.version_repository, SkillVersionRepositoryPort):
            raise RuntimeV2Error(
                "invalid_skill_version_repository",
                "SkillVersion repository Provider returned an invalid repository",
            )

        plugin_config_resolver = operation.require(PLUGIN_CONFIG_APPLICATION_SERVICE_V2)
        if not isinstance(
            plugin_config_resolver,
            PluginConfigApplicationResolverProtocolV2,
        ):
            raise RuntimeV2Error(
                "invalid_plugin_config_application_resolver",
                "Plugin config application service has an invalid resolver",
            )
        plugin_config_repository = plugin_config_resolver.resolve(operation).repository
        if not isinstance(plugin_config_repository, PluginConfigRepositoryProtocolV2):
            raise RuntimeV2Error(
                "invalid_plugin_config_repository",
                "Plugin config Provider returned an invalid repository",
            )

        yield SkillEvolutionHttpApplicationAuthorityV2(
            operation=operation,
            db=db,
            evolution_repository=evolution_repository,
            skill_repository=skill_services.repository,
            skill_version_repository=skill_services.version_repository,
            plugin_config_repository=plugin_config_repository,
        )


__all__ = [
    "SkillEvolutionHttpApplicationAuthorityV2",
    "skill_evolution_http_application_authority_v2",
]
