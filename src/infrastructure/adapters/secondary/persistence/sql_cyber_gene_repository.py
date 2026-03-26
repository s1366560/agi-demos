"""SQLAlchemy repository for CyberGene persistence."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.workspace.cyber_gene import (
    CyberGene,
    CyberGeneCategory,
)
from src.domain.ports.repositories.workspace.cyber_gene_repository import (
    CyberGeneRepository,
)
from src.infrastructure.adapters.secondary.common.base_repository import (
    BaseRepository,
)
from src.infrastructure.adapters.secondary.persistence.models import (
    CyberGeneModel,
)


class SqlCyberGeneRepository(
    BaseRepository[CyberGene, CyberGeneModel],
    CyberGeneRepository,
):
    _model_class = CyberGeneModel

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    async def find_by_workspace(
        self,
        workspace_id: str,
        category: str | None = None,
        is_active: bool | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[CyberGene]:
        query = select(CyberGeneModel).where(CyberGeneModel.workspace_id == workspace_id)
        if category is not None:
            query = query.where(CyberGeneModel.category == category)
        if is_active is not None:
            query = query.where(CyberGeneModel.is_active == is_active)
        query = query.order_by(CyberGeneModel.created_at.asc()).offset(offset).limit(limit)
        result = await self._session.execute(query)
        rows = result.scalars().all()
        return [obj for row in rows if (obj := self._to_domain(row)) is not None]

    def _to_domain(self, db_model: CyberGeneModel | None) -> CyberGene | None:
        if db_model is None:
            return None
        return CyberGene(
            id=db_model.id,
            workspace_id=db_model.workspace_id,
            name=db_model.name,
            category=CyberGeneCategory(db_model.category),
            description=db_model.description,
            config_json=db_model.config_json,
            version=db_model.version,
            is_active=db_model.is_active,
            created_by=db_model.created_by,
            created_at=db_model.created_at,
            updated_at=db_model.updated_at,
        )

    def _to_db(self, domain_entity: CyberGene) -> CyberGeneModel:
        return CyberGeneModel(
            id=domain_entity.id,
            workspace_id=domain_entity.workspace_id,
            name=domain_entity.name,
            category=domain_entity.category.value,
            description=domain_entity.description,
            config_json=domain_entity.config_json,
            version=domain_entity.version,
            is_active=domain_entity.is_active,
            created_by=domain_entity.created_by,
            created_at=domain_entity.created_at,
            updated_at=domain_entity.updated_at,
        )

    def _update_fields(
        self,
        db_model: CyberGeneModel,
        domain_entity: CyberGene,
    ) -> None:
        db_model.name = domain_entity.name
        db_model.category = domain_entity.category.value
        db_model.description = domain_entity.description
        db_model.config_json = domain_entity.config_json
        db_model.version = domain_entity.version
        db_model.is_active = domain_entity.is_active
        db_model.updated_at = domain_entity.updated_at
