"""SQLAlchemy repository for CyberObjective persistence."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.workspace.cyber_objective import (
    CyberObjective,
    CyberObjectiveType,
)
from src.domain.ports.repositories.workspace.cyber_objective_repository import (
    CyberObjectiveRepository,
)
from src.infrastructure.adapters.secondary.common.base_repository import (
    BaseRepository,
)
from src.infrastructure.adapters.secondary.persistence.models import (
    CyberObjectiveModel,
)


class SqlCyberObjectiveRepository(
    BaseRepository[CyberObjective, CyberObjectiveModel],
    CyberObjectiveRepository,
):
    _model_class = CyberObjectiveModel

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    async def find_by_workspace(
        self,
        workspace_id: str,
        obj_type: str | None = None,
        parent_id: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[CyberObjective]:
        query = select(CyberObjectiveModel).where(CyberObjectiveModel.workspace_id == workspace_id)
        if obj_type is not None:
            query = query.where(CyberObjectiveModel.obj_type == obj_type)
        if parent_id is not None:
            query = query.where(CyberObjectiveModel.parent_id == parent_id)
        query = query.order_by(CyberObjectiveModel.created_at.asc()).offset(offset).limit(limit)
        result = await self._session.execute(query)
        rows = result.scalars().all()
        return [obj for row in rows if (obj := self._to_domain(row)) is not None]

    def _to_domain(self, db_model: CyberObjectiveModel | None) -> CyberObjective | None:
        if db_model is None:
            return None
        return CyberObjective(
            id=db_model.id,
            workspace_id=db_model.workspace_id,
            title=db_model.title,
            description=db_model.description,
            obj_type=CyberObjectiveType(db_model.obj_type),
            parent_id=db_model.parent_id,
            progress=db_model.progress,
            created_by=db_model.created_by,
            created_at=db_model.created_at,
            updated_at=db_model.updated_at,
        )

    def _to_db(self, domain_entity: CyberObjective) -> CyberObjectiveModel:
        return CyberObjectiveModel(
            id=domain_entity.id,
            workspace_id=domain_entity.workspace_id,
            title=domain_entity.title,
            description=domain_entity.description,
            obj_type=domain_entity.obj_type.value,
            parent_id=domain_entity.parent_id,
            progress=domain_entity.progress,
            created_by=domain_entity.created_by,
            created_at=domain_entity.created_at,
            updated_at=domain_entity.updated_at,
        )

    def _update_fields(
        self,
        db_model: CyberObjectiveModel,
        domain_entity: CyberObjective,
    ) -> None:
        db_model.title = domain_entity.title
        db_model.description = domain_entity.description
        db_model.obj_type = domain_entity.obj_type.value
        db_model.parent_id = domain_entity.parent_id
        db_model.progress = domain_entity.progress
        db_model.updated_at = domain_entity.updated_at
