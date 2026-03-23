from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, cast

from sqlalchemy import delete, select
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

if TYPE_CHECKING:
    from src.infrastructure.adapters.secondary.persistence.models import (
        AgentBindingModel,
    )

from src.domain.model.agent.agent_binding import AgentBinding
from src.domain.ports.agent.binding_repository import (
    AgentBindingRepositoryPort,
)
from src.infrastructure.adapters.secondary.common.base_repository import (
    BaseRepository,
)

logger = logging.getLogger(__name__)


class SqlAgentBindingRepository(
    BaseRepository[AgentBinding, object],
    AgentBindingRepositoryPort,
):
    _model_class = None

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)
        self._session = session

    async def create(self, binding: AgentBinding) -> AgentBinding:
        from src.infrastructure.adapters.secondary.persistence.models import (
            AgentBindingModel,
        )

        db_binding = AgentBindingModel(
            id=binding.id,
            tenant_id=binding.tenant_id,
            agent_id=binding.agent_id,
            channel_type=binding.channel_type,
            channel_id=binding.channel_id,
            account_id=binding.account_id,
            peer_id=binding.peer_id,
            group_id=binding.group_id,
            priority=binding.priority,
            enabled=binding.enabled,
            created_at=binding.created_at,
        )

        self._session.add(db_binding)
        await self._session.flush()

        return binding

    async def get_by_id(self, binding_id: str) -> AgentBinding | None:
        from src.infrastructure.adapters.secondary.persistence.models import (
            AgentBindingModel,
        )

        result = await self._session.execute(
            select(AgentBindingModel).where(AgentBindingModel.id == binding_id)
        )
        db_binding = result.scalar_one_or_none()
        return self._to_domain(db_binding) if db_binding else None

    async def delete(self, binding_id: str) -> bool:
        from src.infrastructure.adapters.secondary.persistence.models import (
            AgentBindingModel,
        )

        result = await self._session.execute(
            delete(AgentBindingModel).where(AgentBindingModel.id == binding_id)
        )

        if cast(CursorResult[Any], result).rowcount == 0:
            raise ValueError(f"AgentBinding not found: {binding_id}")
        return True

    async def list_by_agent(
        self,
        agent_id: str,
        enabled_only: bool = False,
    ) -> list[AgentBinding]:
        from src.infrastructure.adapters.secondary.persistence.models import (
            AgentBindingModel,
        )

        query = select(AgentBindingModel).where(AgentBindingModel.agent_id == agent_id)

        if enabled_only:
            query = query.where(AgentBindingModel.enabled.is_(True))

        query = query.order_by(AgentBindingModel.priority.desc())

        result = await self._session.execute(query)
        db_bindings = result.scalars().all()

        return [d for b in db_bindings if (d := self._to_domain(b)) is not None]

    async def list_by_tenant(
        self,
        tenant_id: str,
        enabled_only: bool = False,
    ) -> list[AgentBinding]:
        from src.infrastructure.adapters.secondary.persistence.models import (
            AgentBindingModel,
        )

        query = select(AgentBindingModel).where(AgentBindingModel.tenant_id == tenant_id)

        if enabled_only:
            query = query.where(AgentBindingModel.enabled.is_(True))

        query = query.order_by(AgentBindingModel.created_at.desc())

        result = await self._session.execute(query)
        db_bindings = result.scalars().all()

        return [d for b in db_bindings if (d := self._to_domain(b)) is not None]

    async def resolve_binding(
        self,
        tenant_id: str,
        channel_type: str | None = None,
        channel_id: str | None = None,
        account_id: str | None = None,
        peer_id: str | None = None,
    ) -> AgentBinding | None:
        from src.infrastructure.adapters.secondary.persistence.models import (
            AgentBindingModel,
        )

        query = (
            select(AgentBindingModel)
            .where(AgentBindingModel.tenant_id == tenant_id)
            .where(AgentBindingModel.enabled.is_(True))
        )

        if channel_type is not None:
            query = query.where(AgentBindingModel.channel_type.in_([channel_type, None]))

        result = await self._session.execute(query)
        db_bindings = result.scalars().all()

        candidates = [d for b in db_bindings if (d := self._to_domain(b)) is not None]

        best: AgentBinding | None = None
        best_score = -1

        for candidate in candidates:
            if candidate.channel_id is not None and candidate.channel_id != channel_id:
                continue
            if candidate.account_id is not None and candidate.account_id != account_id:
                continue
            if candidate.peer_id is not None and candidate.peer_id != peer_id:
                continue

            score = candidate.specificity_score
            if score > best_score:
                best_score = score
                best = candidate

        return best

    async def set_enabled(
        self,
        binding_id: str,
        enabled: bool,
    ) -> AgentBinding:
        from src.infrastructure.adapters.secondary.persistence.models import (
            AgentBindingModel,
        )

        result = await self._session.execute(
            select(AgentBindingModel).where(AgentBindingModel.id == binding_id)
        )
        db_binding = result.scalar_one_or_none()

        if not db_binding:
            raise ValueError(f"AgentBinding not found: {binding_id}")

        db_binding.enabled = enabled

        await self._session.flush()

        domain = self._to_domain(db_binding)
        assert domain is not None
        return domain

    async def find_by_group(
        self,
        tenant_id: str,
        group_id: str,
    ) -> list[AgentBinding]:
        from src.infrastructure.adapters.secondary.persistence.models import (
            AgentBindingModel,
        )

        query = (
            select(AgentBindingModel)
            .where(AgentBindingModel.tenant_id == tenant_id)
            .where(AgentBindingModel.group_id == group_id)
            .order_by(AgentBindingModel.priority.desc())
        )

        result = await self._session.execute(query)
        db_bindings = result.scalars().all()

        return [d for b in db_bindings if (d := self._to_domain(b)) is not None]

    def _to_domain(self, db_binding: AgentBindingModel | None) -> AgentBinding | None:
        if db_binding is None:
            return None

        return AgentBinding(
            id=db_binding.id,
            tenant_id=db_binding.tenant_id,
            agent_id=db_binding.agent_id,
            channel_type=db_binding.channel_type,
            channel_id=db_binding.channel_id,
            account_id=db_binding.account_id,
            peer_id=db_binding.peer_id,
            group_id=db_binding.group_id,
            priority=db_binding.priority,
            enabled=db_binding.enabled,
            created_at=db_binding.created_at,
        )
