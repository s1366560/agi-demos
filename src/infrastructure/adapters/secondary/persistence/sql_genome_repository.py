"""SQLAlchemy implementation of GenomeRepository using BaseRepository."""

import logging
from typing import Any, override

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select

from src.domain.model.gene.enums import ContentVisibility
from src.domain.model.gene.gene import Genome
from src.domain.ports.repositories.genome_repository import GenomeRepository
from src.infrastructure.adapters.secondary.common.base_repository import (
    BaseRepository,
    refresh_select_statement,
)
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
    async def find_by_id(self, entity_id: str) -> Genome | None:
        if not entity_id:
            raise ValueError("ID cannot be empty")
        stmt = (
            select(GenomeModel)
            .where(GenomeModel.id == entity_id)
            .where(GenomeModel.deleted_at.is_(None))
        )
        result = await self._session.execute(
            refresh_select_statement(self._refresh_statement(stmt))
        )
        return self._to_domain(result.scalar_one_or_none())

    @override
    async def find_by_slug(self, slug: str, tenant_id: str | None = None) -> Genome | None:
        stmt = (
            select(GenomeModel)
            .where(GenomeModel.slug == slug)
            .where(GenomeModel.deleted_at.is_(None))
        )
        if tenant_id is None:
            stmt = stmt.where(GenomeModel.tenant_id.is_(None))
        else:
            stmt = stmt.where(GenomeModel.tenant_id == tenant_id)
        result = await self._session.execute(
            refresh_select_statement(self._refresh_statement(stmt))
        )
        return self._to_domain(result.scalar_one_or_none())

    @override
    async def find_by_tenant(
        self, tenant_id: str, limit: int = 50, offset: int = 0
    ) -> list[Genome]:
        return await self.find_by_filters(tenant_id=tenant_id, limit=limit, offset=offset)

    @override
    async def find_by_filters(
        self,
        *,
        tenant_id: str,
        include_global: bool = False,
        search: str | None = None,
        visibility: str | None = None,
        is_published: bool | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Genome]:
        filters = self._filters(visibility=visibility, is_published=is_published)
        stmt = self._build_active_query(filters=filters)
        stmt = self._apply_tenant_scope(stmt, tenant_id, include_global=include_global)
        stmt = self._apply_search_filter(stmt, search)
        stmt = self._apply_listing_order(stmt).offset(offset).limit(limit)
        result = await self._session.execute(
            refresh_select_statement(self._refresh_statement(stmt))
        )
        db_genomes = result.scalars().all()
        return [d for genome in db_genomes if (d := self._to_domain(genome)) is not None]

    @override
    async def count_by_filters(
        self,
        *,
        tenant_id: str,
        include_global: bool = False,
        search: str | None = None,
        visibility: str | None = None,
        is_published: bool | None = None,
    ) -> int:
        filters = self._filters(visibility=visibility, is_published=is_published)
        stmt = select(func.count()).select_from(GenomeModel).where(GenomeModel.deleted_at.is_(None))
        stmt = self._apply_filters(stmt, **filters)
        stmt = self._apply_tenant_scope(stmt, tenant_id, include_global=include_global)
        stmt = self._apply_search_filter(stmt, search)
        result = await self._session.execute(refresh_select_statement(stmt))
        return result.scalar() or 0

    @staticmethod
    def _filters(
        *,
        visibility: str | None = None,
        is_published: bool | None = None,
    ) -> dict[str, object]:
        filters: dict[str, object] = {}
        if visibility is not None:
            filters["visibility"] = visibility
        if is_published is not None:
            filters["is_published"] = is_published
        return filters

    @staticmethod
    def _apply_search_filter(stmt: Select[Any], search: str | None) -> Select[Any]:
        search_term = search.strip() if search else ""
        if not search_term:
            return stmt
        pattern = f"%{search_term}%"
        return stmt.where(
            or_(
                GenomeModel.name.ilike(pattern),
                GenomeModel.slug.ilike(pattern),
                GenomeModel.description.ilike(pattern),
                GenomeModel.short_description.ilike(pattern),
            )
        )

    @staticmethod
    def _apply_tenant_scope(
        stmt: Select[Any],
        tenant_id: str,
        *,
        include_global: bool = False,
    ) -> Select[Any]:
        if include_global:
            return stmt.where(
                or_(
                    GenomeModel.tenant_id == tenant_id,
                    and_(
                        GenomeModel.tenant_id.is_(None),
                        GenomeModel.is_published.is_(True),
                        GenomeModel.visibility == ContentVisibility.public.value,
                    ),
                )
            )
        return stmt.where(GenomeModel.tenant_id == tenant_id)

    @override
    async def find_featured(self, limit: int = 20) -> list[Genome]:
        stmt = self._apply_listing_order(
            self._build_active_query(filters={"is_featured": True, "is_published": True}).where(
                GenomeModel.tenant_id.is_(None)
            )
        ).limit(limit)
        result = await self._session.execute(
            refresh_select_statement(self._refresh_statement(stmt))
        )
        db_genomes = result.scalars().all()
        return [d for genome in db_genomes if (d := self._to_domain(genome)) is not None]

    def _build_active_query(self, filters: dict[str, Any] | None = None) -> Select[Any]:
        stmt = select(GenomeModel).where(GenomeModel.deleted_at.is_(None))
        if filters:
            stmt = self._apply_filters(stmt, **filters)
        return stmt

    @staticmethod
    def _apply_listing_order(stmt: Select[Any]) -> Select[Any]:
        return stmt.order_by(GenomeModel.created_at.desc(), GenomeModel.id.asc())

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
