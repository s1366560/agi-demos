"""Generation-pinned SkillEvolution persistence for background operations."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.domain.ports.repositories.skill_repository import SkillRepositoryPort
from src.domain.ports.repositories.skill_version_repository import SkillVersionRepositoryPort

from .runtime import OperationContextV2, RuntimeGenerationV2, RuntimeV2Error
from .skill_evolution_repository_services import (
    SKILL_EVOLUTION_REPOSITORY_APPLICATION_SERVICE_V2,
    SkillEvolutionRepositoryApplicationResolverProtocolV2,
    SkillEvolutionRepositoryApplicationServicesV2,
    SkillEvolutionRepositoryProtocolV2,
)
from .skill_repository_services import (
    SKILL_REPOSITORY_APPLICATION_SERVICE_V2,
    SkillRepositoryApplicationResolverProtocolV2,
)


@dataclass(frozen=True, kw_only=True)
class SkillEvolutionRepositoryAuthorityV2:
    """Operation-owned repository and its immutable generation boundary."""

    operation: OperationContextV2
    repository: SkillEvolutionRepositoryProtocolV2
    skill_repository: SkillRepositoryPort
    skill_version_repository: SkillVersionRepositoryPort


type SkillEvolutionRepositoryLeaseV2 = Callable[
    ...,
    AbstractAsyncContextManager[SkillEvolutionRepositoryAuthorityV2],
]


def _require_application_services_v2(
    value: object,
) -> SkillEvolutionRepositoryApplicationServicesV2:
    if not isinstance(value, SkillEvolutionRepositoryApplicationServicesV2):
        raise RuntimeV2Error(
            "invalid_skill_evolution_repository_application_services",
            "SkillEvolution resolver returned invalid application services",
        )
    return value


def _require_repository_v2(value: object) -> SkillEvolutionRepositoryProtocolV2:
    if not isinstance(value, SkillEvolutionRepositoryProtocolV2):
        raise RuntimeV2Error(
            "invalid_skill_evolution_repository",
            "SkillEvolution application services returned an invalid repository",
        )
    return value


@asynccontextmanager
async def lease_skill_evolution_repository_v2(
    *,
    db: AsyncSession,
    tenant_id: str,
) -> AsyncIterator[SkillEvolutionRepositoryAuthorityV2]:
    """Resolve SkillEvolution persistence under one independent background lease."""
    normalized_tenant_id = tenant_id.strip()
    if not normalized_tenant_id:
        raise RuntimeV2Error(
            "skill_evolution_tenant_missing",
            "SkillEvolution repository lease requires a non-empty tenant_id",
        )

    # boundary imports builtin definitions, so keep this import at the operation edge.
    from .boundary import (
        OPERATION_DB_SESSION_SERVICE_V2,
        OPERATION_IDENTITY_SERVICE_V2,
        OPERATION_METADATA_SERVICE_V2,
    )

    async with _capture_or_background_generation(normalized_tenant_id) as (generation, scope):
        operation = OperationContextV2(
            generation=generation,
            operation_id=(f"skill-evolution-repository:{normalized_tenant_id}:{uuid4().hex}"),
            scope=scope,
        )
        async with operation:
            _ = operation.provide(OPERATION_DB_SESSION_SERVICE_V2, db)
            _ = operation.provide(
                OPERATION_IDENTITY_SERVICE_V2,
                {"tenant_id": normalized_tenant_id},
            )
            _ = operation.provide(
                OPERATION_METADATA_SERVICE_V2,
                {
                    "kind": "background-authority",
                    "consumer": "skill-evolution-repository",
                },
            )
            resolver = operation.require(SKILL_EVOLUTION_REPOSITORY_APPLICATION_SERVICE_V2)
            if not isinstance(
                resolver,
                SkillEvolutionRepositoryApplicationResolverProtocolV2,
            ):
                raise RuntimeV2Error(
                    "invalid_skill_evolution_repository_application_resolver",
                    "Resolved SkillEvolution application service has an invalid resolver",
                )
            services = _require_application_services_v2(resolver.resolve(operation))
            repository = _require_repository_v2(services.repository)
            skill_resolver = operation.require(SKILL_REPOSITORY_APPLICATION_SERVICE_V2)
            if not isinstance(
                skill_resolver,
                SkillRepositoryApplicationResolverProtocolV2,
            ):
                raise RuntimeV2Error(
                    "invalid_skill_repository_application_resolver",
                    "Resolved Skill application service has an invalid resolver",
                )
            skill_services = skill_resolver.resolve(operation)
            if not isinstance(skill_services.repository, SkillRepositoryPort):
                raise RuntimeV2Error(
                    "invalid_skill_repository",
                    "Skill application services returned an invalid repository",
                )
            if not isinstance(
                skill_services.version_repository,
                SkillVersionRepositoryPort,
            ):
                raise RuntimeV2Error(
                    "invalid_skill_version_repository",
                    "Skill application services returned an invalid version repository",
                )
            yield SkillEvolutionRepositoryAuthorityV2(
                operation=operation,
                repository=repository,
                skill_repository=skill_services.repository,
                skill_version_repository=skill_services.version_repository,
            )


__all__ = [
    "SkillEvolutionRepositoryAuthorityV2",
    "SkillEvolutionRepositoryLeaseV2",
    "lease_skill_evolution_repository_v2",
]


@asynccontextmanager
async def _capture_or_background_generation(
    tenant_id: str,
) -> AsyncIterator[tuple[RuntimeGenerationV2, ScopeV2]]:
    from .boundary import current_process_generation_host_v2, pin_generation_v2
    from .skill_evolution_capture_admission_v2 import current_worker_capture_operation_v2

    capture = current_worker_capture_operation_v2()
    if capture is not None:
        if capture.context.scope.tenant_id != tenant_id:
            raise RuntimeV2Error(
                "skill_capture_scope_mismatch", "capture repository tenant differs"
            )
        # The synchronous caller still owns the admitted operation's generation lease.
        yield capture.generation, capture.context.scope
        return
    host = current_process_generation_host_v2()
    async with pin_generation_v2(host) as generation:
        yield generation, ScopeV2(kind=ScopeKindV2.TENANT, tenant_id=tenant_id)
