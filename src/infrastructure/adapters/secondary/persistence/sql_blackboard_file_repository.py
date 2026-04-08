"""SQLAlchemy repository for blackboard files."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.workspace.blackboard_file import BlackboardFile
from src.domain.ports.repositories.workspace.blackboard_file_repository import (
    BlackboardFileRepository,
)
from src.infrastructure.adapters.secondary.common.base_repository import BaseRepository
from src.infrastructure.adapters.secondary.persistence.models import BlackboardFileModel


class SqlBlackboardFileRepository(
    BaseRepository[BlackboardFile, BlackboardFileModel], BlackboardFileRepository
):
    """SQLAlchemy implementation of BlackboardFileRepository."""

    _model_class = BlackboardFileModel

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    async def list_by_workspace(
        self,
        workspace_id: str,
        parent_path: str = "/",
    ) -> list[BlackboardFile]:
        query = (
            select(BlackboardFileModel)
            .where(
                BlackboardFileModel.workspace_id == workspace_id,
                BlackboardFileModel.parent_path == parent_path,
            )
            .order_by(
                BlackboardFileModel.is_directory.desc(),
                BlackboardFileModel.name.asc(),
            )
        )
        result = await self._session.execute(query)
        rows = result.scalars().all()
        return [f for row in rows if (f := self._to_domain(row)) is not None]

    def _to_domain(self, db_model: BlackboardFileModel | None) -> BlackboardFile | None:
        if db_model is None:
            return None
        return BlackboardFile(
            id=db_model.id,
            workspace_id=db_model.workspace_id,
            parent_path=db_model.parent_path,
            name=db_model.name,
            is_directory=db_model.is_directory,
            file_size=db_model.file_size,
            content_type=db_model.content_type,
            storage_key=db_model.storage_key,
            uploader_type=db_model.uploader_type,
            uploader_id=db_model.uploader_id,
            uploader_name=db_model.uploader_name,
            created_at=db_model.created_at,
        )

    def _to_db(self, domain_entity: BlackboardFile) -> BlackboardFileModel:
        return BlackboardFileModel(
            id=domain_entity.id,
            workspace_id=domain_entity.workspace_id,
            parent_path=domain_entity.parent_path,
            name=domain_entity.name,
            is_directory=domain_entity.is_directory,
            file_size=domain_entity.file_size,
            content_type=domain_entity.content_type,
            storage_key=domain_entity.storage_key,
            uploader_type=domain_entity.uploader_type,
            uploader_id=domain_entity.uploader_id,
            uploader_name=domain_entity.uploader_name,
            created_at=domain_entity.created_at,
        )
