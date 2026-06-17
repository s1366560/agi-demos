"""SQLAlchemy implementation of InstanceGeneRepository using BaseRepository."""

import logging
from typing import Any, override

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select

from src.domain.model.gene.enums import ContentVisibility, EffectMetricType, InstanceGeneStatus
from src.domain.model.gene.instance_gene import GeneEffectLog, InstanceGene
from src.domain.ports.repositories.instance_gene_repository import (
    InstanceGeneRepository,
)
from src.infrastructure.adapters.secondary.common.base_repository import (
    BaseRepository,
    refresh_select_statement,
)
from src.infrastructure.adapters.secondary.persistence.models import (
    GeneEffectLogModel,
    GeneMarketModel,
    InstanceGeneModel,
)

logger = logging.getLogger(__name__)


class SqlInstanceGeneRepository(
    BaseRepository[InstanceGene, InstanceGeneModel], InstanceGeneRepository
):
    """SQLAlchemy implementation of InstanceGeneRepository."""

    _model_class = InstanceGeneModel

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    @override
    async def find_by_instance(
        self,
        instance_id: str,
        limit: int = 50,
        offset: int = 0,
        search: str | None = None,
        tenant_id: str | None = None,
    ) -> list[InstanceGene]:
        if limit < 0:
            raise ValueError("Limit must be non-negative")
        if limit == 0:
            return []

        query = self._instance_query(instance_id, search=search, tenant_id=tenant_id).order_by(
            InstanceGeneModel.created_at.desc(), InstanceGeneModel.id.asc()
        )
        query = query.offset(offset).limit(limit)
        result = await self._session.execute(
            refresh_select_statement(self._refresh_statement(query))
        )
        db_models = result.scalars().all()
        return [
            domain
            for db_model in db_models
            if db_model is not None
            if (domain := self._to_domain(db_model)) is not None
        ]

    @override
    async def summarize_by_instance(
        self,
        instance_id: str,
        search: str | None = None,
        tenant_id: str | None = None,
    ) -> tuple[int, int, int]:
        query = select(
            func.count(InstanceGeneModel.id),
            func.coalesce(
                func.sum(
                    case(
                        (
                            InstanceGeneModel.status == InstanceGeneStatus.installed.value,
                            1,
                        ),
                        else_=0,
                    )
                ),
                0,
            ),
            func.coalesce(func.sum(InstanceGeneModel.usage_count), 0),
        )
        query = self._apply_instance_filters(query, instance_id, search=search, tenant_id=tenant_id)
        result = await self._session.execute(refresh_select_statement(query))
        total, installed_total, usage_total = result.one()
        return int(total or 0), int(installed_total or 0), int(usage_total or 0)

    @override
    async def find_by_gene(self, gene_id: str) -> list[InstanceGene]:
        query = (
            select(InstanceGeneModel)
            .where(InstanceGeneModel.gene_id == gene_id)
            .where(InstanceGeneModel.deleted_at.is_(None))
            .order_by(InstanceGeneModel.created_at.desc(), InstanceGeneModel.id.asc())
        )
        result = await self._session.execute(
            refresh_select_statement(self._refresh_statement(query))
        )
        db_models = result.scalars().all()
        return [
            domain
            for db_model in db_models
            if db_model is not None
            if (domain := self._to_domain(db_model)) is not None
        ]

    @override
    async def find_by_instance_and_gene(
        self, instance_id: str, gene_id: str
    ) -> InstanceGene | None:
        return await self.find_one(instance_id=instance_id, gene_id=gene_id)

    def _instance_query(
        self,
        instance_id: str,
        *,
        search: str | None = None,
        tenant_id: str | None = None,
    ) -> Select[Any]:
        query = select(InstanceGeneModel)
        return self._apply_instance_filters(query, instance_id, search=search, tenant_id=tenant_id)

    @staticmethod
    def _apply_instance_filters(
        query: Select[Any],
        instance_id: str,
        *,
        search: str | None,
        tenant_id: str | None,
    ) -> Select[Any]:
        query = query.where(InstanceGeneModel.instance_id == instance_id).where(
            InstanceGeneModel.deleted_at.is_(None)
        )
        search_term = search.strip() if search else ""
        if not search_term:
            return query

        join_conditions = [
            GeneMarketModel.id == InstanceGeneModel.gene_id,
            GeneMarketModel.deleted_at.is_(None),
        ]
        if tenant_id is not None:
            join_conditions.append(
                or_(
                    GeneMarketModel.tenant_id == tenant_id,
                    and_(
                        GeneMarketModel.tenant_id.is_(None),
                        GeneMarketModel.is_published.is_(True),
                        GeneMarketModel.visibility == ContentVisibility.public.value,
                    ),
                )
            )
        pattern = f"%{search_term}%"
        return query.outerjoin(GeneMarketModel, and_(*join_conditions)).where(
            or_(
                InstanceGeneModel.gene_id.ilike(pattern),
                GeneMarketModel.name.ilike(pattern),
                GeneMarketModel.slug.ilike(pattern),
                GeneMarketModel.description.ilike(pattern),
                GeneMarketModel.short_description.ilike(pattern),
                GeneMarketModel.category.ilike(pattern),
            )
        )

    @override
    async def save_effect_log(self, log: GeneEffectLog) -> GeneEffectLog:
        db_log = GeneEffectLogModel(
            id=log.id,
            instance_id=log.instance_id,
            gene_id=log.gene_id,
            metric_type=log.metric_type.value,
            value=log.value,
            context=log.context,
            created_at=log.created_at,
        )
        self._session.add(db_log)
        await self._session.flush()
        return log

    @override
    async def find_effect_logs(
        self, instance_id: str, gene_id: str, limit: int = 100
    ) -> list[GeneEffectLog]:
        query = (
            select(GeneEffectLogModel)
            .where(GeneEffectLogModel.instance_id == instance_id)
            .where(GeneEffectLogModel.gene_id == gene_id)
            .order_by(GeneEffectLogModel.created_at.desc())
            .limit(limit)
        )
        result = await self._session.execute(
            refresh_select_statement(self._refresh_statement(query))
        )
        db_logs = result.scalars().all()
        return [self._log_to_domain(log) for log in db_logs]

    @override
    def _to_domain(self, db_model: InstanceGeneModel | None) -> InstanceGene | None:
        if db_model is None:
            return None
        return InstanceGene(
            id=db_model.id,
            instance_id=db_model.instance_id,
            gene_id=db_model.gene_id,
            genome_id=db_model.genome_id,
            status=InstanceGeneStatus(db_model.status),
            installed_version=db_model.installed_version,
            learning_output=db_model.learning_output,
            config_snapshot=db_model.config_snapshot or {},
            agent_self_eval=db_model.agent_self_eval,
            usage_count=db_model.usage_count,
            variant_published=db_model.variant_published,
            installed_at=db_model.installed_at,
            created_at=db_model.created_at,
            deleted_at=db_model.deleted_at,
        )

    @override
    def _to_db(self, domain_entity: InstanceGene) -> InstanceGeneModel:
        return InstanceGeneModel(
            id=domain_entity.id,
            instance_id=domain_entity.instance_id,
            gene_id=domain_entity.gene_id,
            genome_id=domain_entity.genome_id,
            status=domain_entity.status.value,
            installed_version=domain_entity.installed_version,
            learning_output=domain_entity.learning_output,
            config_snapshot=domain_entity.config_snapshot,
            agent_self_eval=domain_entity.agent_self_eval,
            usage_count=domain_entity.usage_count,
            variant_published=domain_entity.variant_published,
            installed_at=domain_entity.installed_at,
            created_at=domain_entity.created_at,
            deleted_at=domain_entity.deleted_at,
        )

    @override
    def _update_fields(self, db_model: InstanceGeneModel, domain_entity: InstanceGene) -> None:
        db_model.genome_id = domain_entity.genome_id
        db_model.status = domain_entity.status.value
        db_model.installed_version = domain_entity.installed_version
        db_model.learning_output = domain_entity.learning_output
        db_model.config_snapshot = domain_entity.config_snapshot
        db_model.agent_self_eval = domain_entity.agent_self_eval
        db_model.usage_count = domain_entity.usage_count
        db_model.variant_published = domain_entity.variant_published
        db_model.installed_at = domain_entity.installed_at
        db_model.deleted_at = domain_entity.deleted_at

    @staticmethod
    def _log_to_domain(db_log: GeneEffectLogModel) -> GeneEffectLog:
        return GeneEffectLog(
            id=db_log.id,
            instance_id=db_log.instance_id,
            gene_id=db_log.gene_id,
            metric_type=EffectMetricType(db_log.metric_type),
            value=db_log.value,
            context=db_log.context or {},
            created_at=db_log.created_at,
        )
