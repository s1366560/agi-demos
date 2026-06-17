"""SQLAlchemy implementation of EvolutionEventRepository using BaseRepository."""

import logging
from typing import Any, override

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select

from src.domain.model.gene.enums import EvolutionEventType
from src.domain.model.gene.instance_gene import EvolutionEvent
from src.domain.ports.repositories.evolution_event_repository import (
    EvolutionEventRepository,
)
from src.infrastructure.adapters.secondary.common.base_repository import (
    BaseRepository,
    refresh_select_statement,
)
from src.infrastructure.adapters.secondary.persistence.models import (
    EvolutionEventModel,
    InstanceModel,
)

logger = logging.getLogger(__name__)


class SqlEvolutionEventRepository(
    BaseRepository[EvolutionEvent, EvolutionEventModel], EvolutionEventRepository
):
    """SQLAlchemy implementation of EvolutionEventRepository."""

    _model_class = EvolutionEventModel

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    @override
    async def find_by_instance(
        self, instance_id: str, limit: int = 100, offset: int = 0
    ) -> list[EvolutionEvent]:
        query = self._build_query(
            filters={"instance_id": instance_id},
            order_by="created_at",
            order_desc=True,
        ).order_by(EvolutionEventModel.id.asc())
        query = query.offset(offset).limit(limit)
        result = await self._session.execute(
            refresh_select_statement(self._refresh_statement(query))
        )
        db_events = result.scalars().all()
        return [d for e in db_events if (d := self._to_domain(e)) is not None]

    @override
    async def find_by_gene(
        self, gene_id: str, limit: int = 100, offset: int = 0
    ) -> list[EvolutionEvent]:
        query = self._build_query(
            filters={"gene_id": gene_id},
            order_by="created_at",
            order_desc=True,
        ).order_by(EvolutionEventModel.id.asc())
        query = query.offset(offset).limit(limit)
        result = await self._session.execute(
            refresh_select_statement(self._refresh_statement(query))
        )
        db_events = result.scalars().all()
        return [d for e in db_events if (d := self._to_domain(e)) is not None]

    @override
    async def find_by_filters(
        self,
        *,
        tenant_id: str | None = None,
        instance_id: str | None = None,
        gene_id: str | None = None,
        event_type: EvolutionEventType | str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[EvolutionEvent]:
        filters = self._filters(
            instance_id=instance_id,
            gene_id=gene_id,
            event_type=event_type,
        )
        query = select(EvolutionEventModel)
        query = self._apply_filters(query, **filters)
        query = self._apply_tenant_scope(query, tenant_id)
        query = query.order_by(EvolutionEventModel.created_at.desc(), EvolutionEventModel.id.asc())
        query = query.offset(offset).limit(limit)
        result = await self._session.execute(
            refresh_select_statement(self._refresh_statement(query))
        )
        db_events = result.scalars().all()
        return [d for e in db_events if (d := self._to_domain(e)) is not None]

    @override
    async def count_by_filters(
        self,
        *,
        tenant_id: str | None = None,
        instance_id: str | None = None,
        gene_id: str | None = None,
        event_type: EvolutionEventType | str | None = None,
    ) -> int:
        filters = self._filters(
            instance_id=instance_id,
            gene_id=gene_id,
            event_type=event_type,
        )
        query = select(func.count()).select_from(EvolutionEventModel)
        query = self._apply_filters(query, **filters)
        query = self._apply_tenant_scope(query, tenant_id)
        result = await self._session.execute(refresh_select_statement(query))
        return result.scalar() or 0

    @staticmethod
    def _filters(
        *,
        instance_id: str | None = None,
        gene_id: str | None = None,
        event_type: EvolutionEventType | str | None = None,
    ) -> dict[str, object]:
        filters: dict[str, object] = {}
        if instance_id is not None:
            filters["instance_id"] = instance_id
        if gene_id is not None:
            filters["gene_id"] = gene_id
        if event_type is not None:
            filters["event_type"] = (
                event_type.value if isinstance(event_type, EvolutionEventType) else event_type
            )
        return filters

    @staticmethod
    def _apply_tenant_scope(stmt: Select[Any], tenant_id: str | None) -> Select[Any]:
        if tenant_id is None:
            return stmt
        return stmt.join(
            InstanceModel,
            EvolutionEventModel.instance_id == InstanceModel.id,
        ).where(
            InstanceModel.tenant_id == tenant_id,
            InstanceModel.deleted_at.is_(None),
        )

    @override
    def _to_domain(self, db_model: EvolutionEventModel | None) -> EvolutionEvent | None:
        if db_model is None:
            return None
        return EvolutionEvent(
            id=db_model.id,
            instance_id=db_model.instance_id,
            gene_id=db_model.gene_id,
            genome_id=db_model.genome_id,
            event_type=EvolutionEventType(db_model.event_type),
            gene_name=db_model.gene_name,
            gene_slug=db_model.gene_slug,
            details=db_model.details or {},
            created_at=db_model.created_at,
        )

    @override
    def _to_db(self, domain_entity: EvolutionEvent) -> EvolutionEventModel:
        return EvolutionEventModel(
            id=domain_entity.id,
            instance_id=domain_entity.instance_id,
            gene_id=domain_entity.gene_id,
            genome_id=domain_entity.genome_id,
            event_type=domain_entity.event_type.value,
            gene_name=domain_entity.gene_name,
            gene_slug=domain_entity.gene_slug,
            details=domain_entity.details,
            created_at=domain_entity.created_at,
        )

    @override
    def _update_fields(self, db_model: EvolutionEventModel, domain_entity: EvolutionEvent) -> None:
        db_model.gene_id = domain_entity.gene_id
        db_model.genome_id = domain_entity.genome_id
        db_model.event_type = domain_entity.event_type.value
        db_model.gene_name = domain_entity.gene_name
        db_model.gene_slug = domain_entity.gene_slug
        db_model.details = domain_entity.details
