"""SQLAlchemy repository for WorkspaceMember persistence."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.workspace.workspace_member import WorkspaceMember
from src.domain.model.workspace.workspace_role import WorkspaceRole
from src.domain.ports.repositories.workspace.workspace_member_repository import (
    WorkspaceMemberRepository,
)
from src.infrastructure.adapters.secondary.common.base_repository import BaseRepository
from src.infrastructure.adapters.secondary.persistence.models import WorkspaceMemberModel


class SqlWorkspaceMemberRepository(
    BaseRepository[WorkspaceMember, WorkspaceMemberModel], WorkspaceMemberRepository
):
    """SQLAlchemy implementation of WorkspaceMemberRepository."""

    _model_class = WorkspaceMemberModel

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    async def find_by_workspace(
        self,
        workspace_id: str,
        limit: int = 100,
        offset: int = 0,
    ) -> list[WorkspaceMember]:
        query = (
            select(WorkspaceMemberModel)
            .where(WorkspaceMemberModel.workspace_id == workspace_id)
            .order_by(WorkspaceMemberModel.created_at.asc())
            .offset(offset)
            .limit(limit)
        )
        result = await self._session.execute(query)
        rows = result.scalars().all()
        return [m for row in rows if (m := self._to_domain(row)) is not None]

    async def find_by_workspace_and_user(
        self,
        workspace_id: str,
        user_id: str,
    ) -> WorkspaceMember | None:
        query = select(WorkspaceMemberModel).where(
            WorkspaceMemberModel.workspace_id == workspace_id,
            WorkspaceMemberModel.user_id == user_id,
        )
        result = await self._session.execute(query)
        row = result.scalar_one_or_none()
        return self._to_domain(row) if row else None

    def _to_domain(self, db_member: WorkspaceMemberModel | None) -> WorkspaceMember | None:
        if db_member is None:
            return None

        return WorkspaceMember(
            id=db_member.id,
            workspace_id=db_member.workspace_id,
            user_id=db_member.user_id,
            role=WorkspaceRole(db_member.role),
            invited_by=db_member.invited_by,
            created_at=db_member.created_at,
            updated_at=db_member.updated_at,
        )

    def _to_db(self, domain_entity: WorkspaceMember) -> WorkspaceMemberModel:
        return WorkspaceMemberModel(
            id=domain_entity.id,
            workspace_id=domain_entity.workspace_id,
            user_id=domain_entity.user_id,
            role=domain_entity.role.value,
            invited_by=domain_entity.invited_by,
            created_at=domain_entity.created_at,
            updated_at=domain_entity.updated_at,
        )

    def _update_fields(
        self,
        db_model: WorkspaceMemberModel,
        domain_entity: WorkspaceMember,
    ) -> None:
        db_model.role = domain_entity.role.value
        db_model.invited_by = domain_entity.invited_by
        db_model.updated_at = domain_entity.updated_at
