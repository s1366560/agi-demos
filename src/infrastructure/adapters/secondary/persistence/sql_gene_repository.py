"""SQLAlchemy implementation of GeneRepository using BaseRepository."""

import logging
from typing import Any, override

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select

from src.domain.model.gene.enums import ContentVisibility, GeneReviewStatus, GeneSource
from src.domain.model.gene.gene import Gene
from src.domain.ports.repositories.gene_repository import GeneRepository
from src.infrastructure.adapters.secondary.common.base_repository import (
    BaseRepository,
    refresh_select_statement,
)
from src.infrastructure.adapters.secondary.persistence.models import (
    GeneMarketModel,
)

logger = logging.getLogger(__name__)


class SqlGeneRepository(BaseRepository[Gene, GeneMarketModel], GeneRepository):
    """SQLAlchemy implementation of GeneRepository."""

    _model_class = GeneMarketModel

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    @override
    async def find_by_slug(self, slug: str) -> Gene | None:
        return await self.find_one(slug=slug)

    @override
    async def find_by_tenant(self, tenant_id: str, limit: int = 50, offset: int = 0) -> list[Gene]:
        return await self.list_all(limit=limit, offset=offset, tenant_id=tenant_id)

    @override
    async def find_by_filters(
        self,
        *,
        tenant_id: str | None = None,
        category: str | None = None,
        search: str | None = None,
        visibility: str | None = None,
        is_published: bool | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Gene]:
        filters = self._filters(
            tenant_id=tenant_id,
            category=category,
            visibility=visibility,
            is_published=is_published,
        )
        stmt = self._build_query(filters=filters)
        stmt = self._apply_search_filter(stmt, search)
        stmt = stmt.offset(offset).limit(limit)
        result = await self._session.execute(
            refresh_select_statement(self._refresh_statement(stmt))
        )
        db_genes = result.scalars().all()
        return [d for g in db_genes if (d := self._to_domain(g)) is not None]

    @override
    async def count_by_filters(
        self,
        *,
        tenant_id: str | None = None,
        category: str | None = None,
        search: str | None = None,
        visibility: str | None = None,
        is_published: bool | None = None,
    ) -> int:
        filters = self._filters(
            tenant_id=tenant_id,
            category=category,
            visibility=visibility,
            is_published=is_published,
        )
        stmt = select(func.count()).select_from(GeneMarketModel)
        stmt = self._apply_filters(stmt, **filters)
        stmt = self._apply_search_filter(stmt, search)
        result = await self._session.execute(refresh_select_statement(stmt))
        return result.scalar() or 0

    @override
    async def search(
        self,
        query: str,
        category: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Gene]:
        stmt = self._build_query(filters={"is_published": True})
        if category is not None:
            stmt = stmt.where(GeneMarketModel.category == category)
        if query:
            pattern = f"%{query}%"
            stmt = stmt.where(
                or_(
                    GeneMarketModel.name.ilike(pattern),
                    GeneMarketModel.description.ilike(pattern),
                )
            )
        stmt = stmt.offset(offset).limit(limit)
        result = await self._session.execute(
            refresh_select_statement(self._refresh_statement(stmt))
        )
        db_genes = result.scalars().all()
        return [d for g in db_genes if (d := self._to_domain(g)) is not None]

    @staticmethod
    def _filters(
        *,
        tenant_id: str | None = None,
        category: str | None = None,
        visibility: str | None = None,
        is_published: bool | None = None,
    ) -> dict[str, object]:
        filters: dict[str, object] = {}
        if tenant_id is not None:
            filters["tenant_id"] = tenant_id
        if category is not None:
            filters["category"] = category
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
                GeneMarketModel.name.ilike(pattern),
                GeneMarketModel.slug.ilike(pattern),
                GeneMarketModel.description.ilike(pattern),
                GeneMarketModel.short_description.ilike(pattern),
            )
        )

    @override
    async def find_featured(self, limit: int = 20) -> list[Gene]:
        return await self.list_all(limit=limit, is_featured=True, is_published=True)

    @override
    def _to_domain(self, db_model: GeneMarketModel | None) -> Gene | None:
        if db_model is None:
            return None
        return Gene(
            id=db_model.id,
            name=db_model.name,
            slug=db_model.slug,
            tenant_id=db_model.tenant_id,
            description=db_model.description,
            short_description=db_model.short_description,
            category=db_model.category,
            tags=db_model.tags or [],
            source=GeneSource(db_model.source),
            source_ref=db_model.source_ref,
            icon=db_model.icon,
            version=db_model.version,
            manifest=db_model.manifest or {},
            dependencies=db_model.dependencies or [],
            synergies=db_model.synergies or [],
            parent_gene_id=db_model.parent_gene_id,
            created_by_instance_id=db_model.created_by_instance_id,
            install_count=db_model.install_count,
            avg_rating=db_model.avg_rating,
            effectiveness_score=db_model.effectiveness_score,
            is_featured=db_model.is_featured,
            review_status=GeneReviewStatus(db_model.review_status),
            is_published=db_model.is_published,
            visibility=ContentVisibility(db_model.visibility),
            created_by=db_model.created_by,
            created_at=db_model.created_at,
            updated_at=db_model.updated_at,
            deleted_at=db_model.deleted_at,
        )

    @override
    def _to_db(self, domain_entity: Gene) -> GeneMarketModel:
        return GeneMarketModel(
            id=domain_entity.id,
            name=domain_entity.name,
            slug=domain_entity.slug,
            tenant_id=domain_entity.tenant_id,
            description=domain_entity.description,
            short_description=domain_entity.short_description,
            category=domain_entity.category,
            tags=domain_entity.tags,
            source=domain_entity.source.value,
            source_ref=domain_entity.source_ref,
            icon=domain_entity.icon,
            version=domain_entity.version,
            manifest=domain_entity.manifest,
            dependencies=domain_entity.dependencies,
            synergies=domain_entity.synergies,
            parent_gene_id=domain_entity.parent_gene_id,
            created_by_instance_id=domain_entity.created_by_instance_id,
            install_count=domain_entity.install_count,
            avg_rating=domain_entity.avg_rating,
            effectiveness_score=domain_entity.effectiveness_score,
            is_featured=domain_entity.is_featured,
            review_status=domain_entity.review_status.value,
            is_published=domain_entity.is_published,
            visibility=domain_entity.visibility.value,
            created_by=domain_entity.created_by,
            created_at=domain_entity.created_at,
            updated_at=domain_entity.updated_at,
            deleted_at=domain_entity.deleted_at,
        )

    @override
    def _update_fields(self, db_model: GeneMarketModel, domain_entity: Gene) -> None:
        db_model.name = domain_entity.name
        db_model.slug = domain_entity.slug
        db_model.tenant_id = domain_entity.tenant_id
        db_model.description = domain_entity.description
        db_model.short_description = domain_entity.short_description
        db_model.category = domain_entity.category
        db_model.tags = domain_entity.tags
        db_model.source = domain_entity.source.value
        db_model.source_ref = domain_entity.source_ref
        db_model.icon = domain_entity.icon
        db_model.version = domain_entity.version
        db_model.manifest = domain_entity.manifest
        db_model.dependencies = domain_entity.dependencies
        db_model.synergies = domain_entity.synergies
        db_model.parent_gene_id = domain_entity.parent_gene_id
        db_model.created_by_instance_id = domain_entity.created_by_instance_id
        db_model.install_count = domain_entity.install_count
        db_model.avg_rating = domain_entity.avg_rating
        db_model.effectiveness_score = domain_entity.effectiveness_score
        db_model.is_featured = domain_entity.is_featured
        db_model.review_status = domain_entity.review_status.value
        db_model.is_published = domain_entity.is_published
        db_model.visibility = domain_entity.visibility.value
        db_model.updated_at = domain_entity.updated_at
        db_model.deleted_at = domain_entity.deleted_at
