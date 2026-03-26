from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.workspace.workspace_message import (
    MessageSenderType,
    WorkspaceMessage,
)
from src.domain.ports.repositories.workspace.workspace_message_repository import (
    WorkspaceMessageRepository,
)
from src.infrastructure.adapters.secondary.common.base_repository import BaseRepository
from src.infrastructure.adapters.secondary.persistence.models import WorkspaceMessageModel


class SqlWorkspaceMessageRepository(
    BaseRepository[WorkspaceMessage, WorkspaceMessageModel], WorkspaceMessageRepository
):
    _model_class = WorkspaceMessageModel

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    async def find_by_workspace(
        self,
        workspace_id: str,
        limit: int = 50,
        offset: int = 0,
        before: str | None = None,
    ) -> list[WorkspaceMessage]:
        query = select(WorkspaceMessageModel).where(
            WorkspaceMessageModel.workspace_id == workspace_id,
        )
        if before is not None:
            before_msg = await self._session.execute(
                select(WorkspaceMessageModel.created_at).where(WorkspaceMessageModel.id == before)
            )
            before_ts = before_msg.scalar_one_or_none()
            if before_ts is not None:
                query = query.where(WorkspaceMessageModel.created_at < before_ts)

        query = query.order_by(WorkspaceMessageModel.created_at.asc()).offset(offset).limit(limit)
        result = await self._session.execute(query)
        rows = result.scalars().all()
        return [m for row in rows if (m := self._to_domain(row)) is not None]

    async def find_thread(
        self,
        parent_message_id: str,
        limit: int = 50,
        offset: int = 0,
    ) -> list[WorkspaceMessage]:
        query = (
            select(WorkspaceMessageModel)
            .where(WorkspaceMessageModel.parent_message_id == parent_message_id)
            .order_by(WorkspaceMessageModel.created_at.asc())
            .offset(offset)
            .limit(limit)
        )
        result = await self._session.execute(query)
        rows = result.scalars().all()
        return [m for row in rows if (m := self._to_domain(row)) is not None]

    def _to_domain(self, db_model: WorkspaceMessageModel | None) -> WorkspaceMessage | None:
        if db_model is None:
            return None
        return WorkspaceMessage(
            id=db_model.id,
            workspace_id=db_model.workspace_id,
            sender_id=db_model.sender_id,
            sender_type=MessageSenderType(db_model.sender_type),
            content=db_model.content,
            mentions=db_model.mentions_json or [],
            parent_message_id=db_model.parent_message_id,
            metadata=db_model.metadata_json or {},
            created_at=db_model.created_at,
        )

    def _to_db(self, domain_entity: WorkspaceMessage) -> WorkspaceMessageModel:
        return WorkspaceMessageModel(
            id=domain_entity.id,
            workspace_id=domain_entity.workspace_id,
            sender_id=domain_entity.sender_id,
            sender_type=domain_entity.sender_type.value,
            content=domain_entity.content,
            mentions_json=domain_entity.mentions,
            parent_message_id=domain_entity.parent_message_id,
            metadata_json=domain_entity.metadata,
            created_at=domain_entity.created_at,
        )
