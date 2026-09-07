"""Generation-owned Provider/Consumer seams for Gene marketplace operations."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol, TypedDict, runtime_checkable

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.services.gene_service import GeneService
from src.infrastructure.adapters.secondary.common.base_repository import refresh_select_statement
from src.infrastructure.adapters.secondary.persistence.models import GeneMarketModel, InstanceModel
from src.infrastructure.adapters.secondary.persistence.sql_evolution_event_repository import (
    SqlEvolutionEventRepository,
)
from src.infrastructure.adapters.secondary.persistence.sql_gene_rating_repository import (
    SqlGeneRatingRepository,
)
from src.infrastructure.adapters.secondary.persistence.sql_gene_repository import SqlGeneRepository
from src.infrastructure.adapters.secondary.persistence.sql_gene_review_repository import (
    SqlGeneReviewRepository,
)
from src.infrastructure.adapters.secondary.persistence.sql_genome_repository import (
    SqlGenomeRepository,
)
from src.infrastructure.adapters.secondary.persistence.sql_instance_gene_repository import (
    SqlInstanceGeneRepository,
)

from .runtime import (
    ContextV2,
    OperationContextV2,
    PluginDefinitionV2,
    RuntimeV2Error,
    generated_contract_digest_v2,
)

GENE_PROVIDER_MODULE_V2 = "builtin://memstack/persistence/gene-provider"
GENE_PROVIDER_SERVICE_V2 = "service:persistence.gene-provider"
GENE_APPLICATION_MODULE_V2 = "builtin://memstack/application/gene-services"
GENE_APPLICATION_SERVICE_V2 = "service:application.gene-services"
GENE_PROVIDER_INJECT_V2 = "provider"
_OPERATION_DB_SESSION_SERVICE_V2 = "service:operation.db-session"


class GeneMetadataV2(TypedDict):
    """Display metadata exposed to installed-gene response assembly."""

    name: str | None
    description: str | None
    category: str | None


@dataclass(frozen=True, kw_only=True)
class GeneResourceDirectoryV2:
    """Tenant-scoped structural lookups required by Gene handlers."""

    _db: AsyncSession

    async def contains_instance(self, *, instance_id: str, tenant_id: str) -> bool:
        result = await self._db.execute(
            refresh_select_statement(
                select(InstanceModel.id).where(
                    InstanceModel.id == instance_id,
                    InstanceModel.tenant_id == tenant_id,
                    InstanceModel.deleted_at.is_(None),
                )
            )
        )
        return result.scalar_one_or_none() is not None

    async def get_gene_metadata(
        self,
        *,
        gene_ids: set[str],
        tenant_id: str,
    ) -> dict[str, GeneMetadataV2]:
        if not gene_ids:
            return {}
        result = await self._db.execute(
            refresh_select_statement(
                select(
                    GeneMarketModel.id,
                    GeneMarketModel.name,
                    GeneMarketModel.description,
                    GeneMarketModel.category,
                )
                .where(GeneMarketModel.id.in_(gene_ids))
                .where(
                    or_(
                        GeneMarketModel.tenant_id == tenant_id,
                        GeneMarketModel.tenant_id.is_(None),
                    )
                )
                .where(GeneMarketModel.deleted_at.is_(None))
            )
        )
        return {
            gene_id: {
                "name": name,
                "description": description,
                "category": category,
            }
            for gene_id, name, description, category in result.all()
        }


@dataclass(frozen=True, kw_only=True)
class GeneApplicationServicesV2:
    """Operation-owned Gene marketplace service set."""

    genes: GeneService
    resources: GeneResourceDirectoryV2


@runtime_checkable
class GeneServiceFactoryProtocolV2(Protocol):
    """Build Gene services without exposing SQL implementation classes."""

    def build(self, operation: OperationContextV2) -> GeneApplicationServicesV2: ...


@runtime_checkable
class GeneApplicationResolverProtocolV2(Protocol):
    """Resolve Gene services through a declared Provider alias."""

    def resolve(self, operation: OperationContextV2) -> GeneApplicationServicesV2: ...


@dataclass(frozen=True, kw_only=True)
class SqlGeneServiceFactoryV2:
    """Bind Gene repositories to the operation's exact AsyncSession."""

    def build(self, operation: OperationContextV2) -> GeneApplicationServicesV2:
        db = operation.require(_OPERATION_DB_SESSION_SERVICE_V2)
        if not isinstance(db, AsyncSession):
            raise RuntimeV2Error(
                "invalid_operation_db_session",
                "gene services require an AsyncSession operation service",
            )
        return GeneApplicationServicesV2(
            genes=GeneService(
                gene_repo=SqlGeneRepository(db),
                genome_repo=SqlGenomeRepository(db),
                instance_gene_repo=SqlInstanceGeneRepository(db),
                gene_rating_repo=SqlGeneRatingRepository(db),
                evolution_event_repo=SqlEvolutionEventRepository(db),
                gene_review_repo=SqlGeneReviewRepository(db),
            ),
            resources=GeneResourceDirectoryV2(_db=db),
        )


@dataclass(frozen=True, kw_only=True)
class GeneApplicationResolverV2:
    """Consumer seam for an explicitly selected Gene Provider."""

    provider: GeneServiceFactoryProtocolV2

    def resolve(self, operation: OperationContextV2) -> GeneApplicationServicesV2:
        return self.provider.build(operation)


def _apply_gene_provider_v2(
    context: ContextV2,
    config: Mapping[str, Any],
) -> None:
    if config.get("strategy") != "operation-async-session":
        raise ValueError("gene provider requires strategy operation-async-session")
    _ = context.provide(
        GENE_PROVIDER_SERVICE_V2,
        SqlGeneServiceFactoryV2(),
        label="gene-provider",
    )


def _apply_gene_application_v2(
    context: ContextV2,
    config: Mapping[str, Any],
) -> None:
    if config.get("strategy") != "operation-scoped-provider":
        raise ValueError("gene application resolver requires strategy operation-scoped-provider")
    provider = context.require(GENE_PROVIDER_INJECT_V2)
    if not isinstance(provider, GeneServiceFactoryProtocolV2):
        raise RuntimeV2Error(
            "invalid_gene_provider",
            "gene provider inject does not implement the factory contract",
        )
    _ = context.provide(
        GENE_APPLICATION_SERVICE_V2,
        GeneApplicationResolverV2(provider=provider),
        label="gene-application",
    )


def gene_service_definitions_v2() -> tuple[PluginDefinitionV2, ...]:
    """Return independent Provider and Consumer definitions for Gene operations."""
    return (
        PluginDefinitionV2(
            module_ref=GENE_PROVIDER_MODULE_V2,
            contract_digest=generated_contract_digest_v2(GENE_PROVIDER_MODULE_V2),
            apply=_apply_gene_provider_v2,
        ),
        PluginDefinitionV2(
            module_ref=GENE_APPLICATION_MODULE_V2,
            contract_digest=generated_contract_digest_v2(GENE_APPLICATION_MODULE_V2),
            apply=_apply_gene_application_v2,
        ),
    )


__all__ = [
    "GENE_APPLICATION_MODULE_V2",
    "GENE_APPLICATION_SERVICE_V2",
    "GENE_PROVIDER_INJECT_V2",
    "GENE_PROVIDER_MODULE_V2",
    "GENE_PROVIDER_SERVICE_V2",
    "GeneApplicationResolverProtocolV2",
    "GeneApplicationResolverV2",
    "GeneApplicationServicesV2",
    "GeneMetadataV2",
    "GeneResourceDirectoryV2",
    "GeneServiceFactoryProtocolV2",
    "SqlGeneServiceFactoryV2",
    "gene_service_definitions_v2",
]
