"""SQLAlchemy implementation of GenomeRepository using BaseRepository."""

import logging
from typing import override

from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.gene.enums import ContentVisibility
from src.domain.model.gene.gene import Genome
from src.domain.ports.repositories.genome_repository import GenomeRepository
from src.infrastructure.adapters.secondary.common.base_repository import BaseRepository
from src.infrastructure.adapters.secondary.persistence.models import (
    GenomeModel,
)

logger = logging.getLogger(__name__)


class SqlGenomeRepository(BaseRepository[Genome, GenomeModel], GenomeRepository):
    """SQLAlchemy implementation of GenomeRepository."""

    _model_class = GenomeModel

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    @override
    async def find_by_slug(self, slug: str) -> Genome | None:
        return await self.find_one(slug=slug)

    @override
    async def find_by_tenant(
        self, tenant_id: str, limit: int = 50, offset: int = 0
    ) -> list[Genome]:
        return await self.list_all(limit=limit, offset=offset, tenant_id=tenant_id)

    @override
    async def find_featured(self, limit: int = 20) -> list[Genome]:
        return await self.list_all(limit=limit, is_featured=True, is_published=True)

    @override
    def _to_domain(self, db_model: GenomeModel | None) -> Genome | None:
        if db_model is None:
            return None
        return Genome(
            id=db_model.id,
            name=db_model.name,
            slug=db_model.slug,
            tenant_id=db_model.tenant_id,
            description=db_model.description,
            short_description=db_model.short_description,
            icon=db_model.icon,
            gene_slugs=db_model.gene_slugs or [],
            config_override=db_model.config_override or {},
            install_count=db_model.install_count,
            avg_rating=db_model.avg_rating,
            is_featured=db_model.is_featured,
            is_published=db_model.is_published,
            visibility=ContentVisibility(db_model.visibility),
            created_by=db_model.created_by,
            created_at=db_model.created_at,
            updated_at=db_model.updated_at,
            deleted_at=db_model.deleted_at,
        )

    @override
    def _to_db(self, domain_entity: Genome) -> GenomeModel:
        return GenomeModel(
            id=domain_entity.id,
            name=domain_entity.name,
            slug=domain_entity.slug,
            tenant_id=domain_entity.tenant_id,
            description=domain_entity.description,
            short_description=domain_entity.short_description,
            icon=domain_entity.icon,
            gene_slugs=domain_entity.gene_slugs,
            config_override=domain_entity.config_override,
            install_count=domain_entity.install_count,
            avg_rating=domain_entity.avg_rating,
            is_featured=domain_entity.is_featured,
            is_published=domain_entity.is_published,
            visibility=domain_entity.visibility.value,
            created_by=domain_entity.created_by,
            created_at=domain_entity.created_at,
            updated_at=domain_entity.updated_at,
            deleted_at=domain_entity.deleted_at,
        )

    @override
    def _update_fields(self, db_model: GenomeModel, domain_entity: Genome) -> None:
        db_model.name = domain_entity.name
        db_model.slug = domain_entity.slug
        db_model.tenant_id = domain_entity.tenant_id
        db_model.description = domain_entity.description
        db_model.short_description = domain_entity.short_description
        db_model.icon = domain_entity.icon
        db_model.gene_slugs = domain_entity.gene_slugs
        db_model.config_override = domain_entity.config_override
        db_model.install_count = domain_entity.install_count
        db_model.avg_rating = domain_entity.avg_rating
        db_model.is_featured = domain_entity.is_featured
        db_model.is_published = domain_entity.is_published
        db_model.visibility = domain_entity.visibility.value
        db_model.updated_at = domain_entity.updated_at
        db_model.deleted_at = domain_entity.deleted_at
