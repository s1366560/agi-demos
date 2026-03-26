"""SQLAlchemy repository for WorkspaceAgent persistence."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.workspace.workspace_agent import WorkspaceAgent
from src.domain.ports.repositories.workspace.workspace_agent_repository import (
    WorkspaceAgentRepository,
)
from src.infrastructure.adapters.secondary.common.base_repository import BaseRepository
from src.infrastructure.adapters.secondary.persistence.models import WorkspaceAgentModel


class SqlWorkspaceAgentRepository(
    BaseRepository[WorkspaceAgent, WorkspaceAgentModel], WorkspaceAgentRepository
):
    """SQLAlchemy implementation of WorkspaceAgentRepository."""

    _model_class = WorkspaceAgentModel

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    async def find_by_workspace(
        self,
        workspace_id: str,
        active_only: bool = False,
        limit: int = 100,
        offset: int = 0,
    ) -> list[WorkspaceAgent]:
        query = select(WorkspaceAgentModel).where(WorkspaceAgentModel.workspace_id == workspace_id)
        if active_only:
            query = query.where(WorkspaceAgentModel.is_active.is_(True))
        query = query.order_by(WorkspaceAgentModel.created_at.asc()).offset(offset).limit(limit)
        result = await self._session.execute(query)
        rows = result.scalars().all()
        return [a for row in rows if (a := self._to_domain(row)) is not None]

    def _to_domain(self, db_agent: WorkspaceAgentModel | None) -> WorkspaceAgent | None:
        if db_agent is None:
            return None

        return WorkspaceAgent(
            id=db_agent.id,
            workspace_id=db_agent.workspace_id,
            agent_id=db_agent.agent_id,
            display_name=db_agent.display_name,
            description=db_agent.description,
            config=db_agent.config_json or {},
            is_active=db_agent.is_active,
            hex_q=db_agent.hex_q,
            hex_r=db_agent.hex_r,
            theme_color=db_agent.theme_color,
            label=db_agent.label,
            status=db_agent.status,
            created_at=db_agent.created_at,
            updated_at=db_agent.updated_at,
        )

    def _to_db(self, domain_entity: WorkspaceAgent) -> WorkspaceAgentModel:
        return WorkspaceAgentModel(
            id=domain_entity.id,
            workspace_id=domain_entity.workspace_id,
            agent_id=domain_entity.agent_id,
            display_name=domain_entity.display_name,
            description=domain_entity.description,
            config_json=domain_entity.config,
            is_active=domain_entity.is_active,
            hex_q=domain_entity.hex_q,
            hex_r=domain_entity.hex_r,
            theme_color=domain_entity.theme_color,
            label=domain_entity.label,
            status=domain_entity.status,
            created_at=domain_entity.created_at,
            updated_at=domain_entity.updated_at,
        )

    def _update_fields(self, db_model: WorkspaceAgentModel, domain_entity: WorkspaceAgent) -> None:
        db_model.display_name = domain_entity.display_name
        db_model.description = domain_entity.description
        db_model.config_json = domain_entity.config
        db_model.is_active = domain_entity.is_active
        db_model.hex_q = domain_entity.hex_q
        db_model.hex_r = domain_entity.hex_r
        db_model.theme_color = domain_entity.theme_color
        db_model.label = domain_entity.label
        db_model.status = domain_entity.status
        db_model.updated_at = domain_entity.updated_at
