"""SQLAlchemy implementation of EvolutionEventRepository using BaseRepository."""

import logging
from typing import override

from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.gene.enums import EvolutionEventType
from src.domain.model.gene.instance_gene import EvolutionEvent
from src.domain.ports.repositories.evolution_event_repository import (
    EvolutionEventRepository,
)
from src.infrastructure.adapters.secondary.common.base_repository import BaseRepository
from src.infrastructure.adapters.secondary.persistence.models import (
    EvolutionEventModel,
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
        )
        query = query.offset(offset).limit(limit)
        result = await self._session.execute(query)
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
        )
        query = query.offset(offset).limit(limit)
        result = await self._session.execute(query)
        db_events = result.scalars().all()
        return [d for e in db_events if (d := self._to_domain(e)) is not None]

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
