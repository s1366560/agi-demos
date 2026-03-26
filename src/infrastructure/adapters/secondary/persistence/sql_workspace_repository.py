"""SQLAlchemy repository for Workspace persistence."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.workspace.workspace import Workspace
from src.domain.ports.repositories.workspace.workspace_repository import WorkspaceRepository
from src.infrastructure.adapters.secondary.common.base_repository import BaseRepository
from src.infrastructure.adapters.secondary.persistence.models import WorkspaceModel


class SqlWorkspaceRepository(BaseRepository[Workspace, WorkspaceModel], WorkspaceRepository):
    """SQLAlchemy implementation of WorkspaceRepository."""

    _model_class = WorkspaceModel

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    async def find_by_project(
        self,
        tenant_id: str,
        project_id: str,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Workspace]:
        query = (
            select(WorkspaceModel)
            .where(WorkspaceModel.tenant_id == tenant_id)
            .where(WorkspaceModel.project_id == project_id)
            .order_by(WorkspaceModel.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        result = await self._session.execute(query)
        rows = result.scalars().all()
        return [w for row in rows if (w := self._to_domain(row)) is not None]

    def _to_domain(self, db_workspace: WorkspaceModel | None) -> Workspace | None:
        if db_workspace is None:
            return None

        return Workspace(
            id=db_workspace.id,
            tenant_id=db_workspace.tenant_id,
            project_id=db_workspace.project_id,
            name=db_workspace.name,
            created_by=db_workspace.created_by,
            description=db_workspace.description,
            is_archived=db_workspace.is_archived,
            metadata=db_workspace.metadata_json or {},
            office_status=db_workspace.office_status,
            hex_layout_config=db_workspace.hex_layout_config_json or {},
            created_at=db_workspace.created_at,
            updated_at=db_workspace.updated_at,
        )

    def _to_db(self, domain_entity: Workspace) -> WorkspaceModel:
        return WorkspaceModel(
            id=domain_entity.id,
            tenant_id=domain_entity.tenant_id,
            project_id=domain_entity.project_id,
            name=domain_entity.name,
            created_by=domain_entity.created_by,
            description=domain_entity.description,
            is_archived=domain_entity.is_archived,
            metadata_json=domain_entity.metadata,
            office_status=domain_entity.office_status,
            hex_layout_config_json=domain_entity.hex_layout_config,
            created_at=domain_entity.created_at,
            updated_at=domain_entity.updated_at,
        )

    def _update_fields(self, db_model: WorkspaceModel, domain_entity: Workspace) -> None:
        db_model.name = domain_entity.name
        db_model.description = domain_entity.description
        db_model.is_archived = domain_entity.is_archived
        db_model.metadata_json = domain_entity.metadata
        db_model.office_status = domain_entity.office_status
        db_model.hex_layout_config_json = domain_entity.hex_layout_config
        db_model.updated_at = domain_entity.updated_at
