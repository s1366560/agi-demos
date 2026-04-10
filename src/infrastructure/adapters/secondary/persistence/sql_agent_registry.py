from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, cast

from sqlalchemy import delete, func, or_, select
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

if TYPE_CHECKING:
    from src.infrastructure.adapters.secondary.persistence.models import (
        AgentDefinitionModel,
    )

from src.domain.model.agent.agent_definition import Agent
from src.domain.model.agent.agent_source import AgentSource
from src.domain.model.agent.delegate_config import DelegateConfig
from src.domain.model.agent.session_policy import SessionPolicy
from src.domain.model.agent.subagent import AgentModel, AgentTrigger
from src.domain.model.agent.workspace_config import WorkspaceConfig
from src.domain.ports.agent.agent_registry import AgentRegistryPort
from src.infrastructure.adapters.secondary.common.base_repository import (
    BaseRepository,
)
from src.infrastructure.agent.sisyphus.builtin_agent import (
    BUILTIN_AGENT_NAMESPACE,
    get_builtin_agent_by_id,
    get_builtin_agent_by_name,
    is_builtin_agent_id,
    is_builtin_agent_name,
    list_builtin_agents,
)

logger = logging.getLogger(__name__)


def _dedupe_agents_by_name_prefer_builtin(agents: list[Agent]) -> list[Agent]:
    """Collapse same-name agents while keeping builtin definitions canonical."""
    deduped: list[Agent] = []
    seen: set[str] = set()
    for agent in agents:
        key = agent.name.casefold()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(agent)
    return deduped


class SqlAgentRegistryRepository(
    BaseRepository[Agent, object],
    AgentRegistryPort,
):
    _model_class = None

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)
        self._session = session

    async def create(self, agent: Agent) -> Agent:
        from src.infrastructure.adapters.secondary.persistence.models import (
            AgentDefinitionModel,
        )

        if is_builtin_agent_id(agent.id) or is_builtin_agent_name(agent.name):
            raise ValueError("Built-in agent ids and names are reserved")

        db_agent = AgentDefinitionModel(
            id=agent.id,
            tenant_id=agent.tenant_id,
            project_id=agent.project_id,
            name=agent.name,
            display_name=agent.display_name,
            system_prompt=agent.system_prompt,
            trigger_description=agent.trigger.description,
            trigger_examples=list(agent.trigger.examples),
            trigger_keywords=list(agent.trigger.keywords),
            model=agent.model.value,
            persona_files=list(agent.persona_files),
            allowed_tools=list(agent.allowed_tools),
            allowed_skills=list(agent.allowed_skills),
            allowed_mcp_servers=list(agent.allowed_mcp_servers),
            max_tokens=agent.max_tokens,
            temperature=agent.temperature,
            max_iterations=agent.max_iterations,
            workspace_dir=agent.workspace_dir,
            workspace_config=agent.workspace_config.to_dict(),
            can_spawn=agent.can_spawn,
            max_spawn_depth=agent.max_spawn_depth,
            agent_to_agent_enabled=agent.agent_to_agent_enabled,
            agent_to_agent_allowlist=agent.agent_to_agent_allowlist,
            discoverable=agent.discoverable,
            source=(agent.source.value if isinstance(agent.source, AgentSource) else agent.source),
            enabled=agent.enabled,
            max_retries=agent.max_retries,
            fallback_models=list(agent.fallback_models),
            total_invocations=agent.total_invocations,
            avg_execution_time_ms=agent.avg_execution_time_ms,
            success_rate=agent.success_rate,
            metadata_json=agent.metadata,
            session_policy=(agent.session_policy.to_dict() if agent.session_policy else None),
            delegate_config=(agent.delegate_config.to_dict() if agent.delegate_config else None),
            created_at=agent.created_at,
            updated_at=agent.updated_at,
        )

        self._session.add(db_agent)
        await self._session.flush()

        return agent

    async def get_by_id(
        self,
        agent_id: str,
        *,
        tenant_id: str | None = None,
        project_id: str | None = None,
    ) -> Agent | None:
        builtin_agent = get_builtin_agent_by_id(
            agent_id,
            tenant_id=tenant_id or BUILTIN_AGENT_NAMESPACE,
            project_id=project_id,
        )
        if builtin_agent is not None:
            return builtin_agent

        from src.infrastructure.adapters.secondary.persistence.models import (
            AgentDefinitionModel,
        )

        result = await self._session.execute(
            select(AgentDefinitionModel).where(AgentDefinitionModel.id == agent_id)
        )
        db_agent = result.scalar_one_or_none()
        return self._to_domain(db_agent) if db_agent else None

    async def get_by_name(
        self,
        tenant_id: str,
        name: str,
    ) -> Agent | None:
        builtin_agent = get_builtin_agent_by_name(name, tenant_id=tenant_id)
        if builtin_agent is not None:
            return builtin_agent

        from src.infrastructure.adapters.secondary.persistence.models import (
            AgentDefinitionModel,
        )

        result = await self._session.execute(
            select(AgentDefinitionModel)
            .where(AgentDefinitionModel.tenant_id == tenant_id)
            .where(AgentDefinitionModel.name == name)
        )
        db_agent = result.scalar_one_or_none()
        return self._to_domain(db_agent) if db_agent else None

    async def update(self, agent: Agent) -> Agent:
        if is_builtin_agent_id(agent.id) or is_builtin_agent_name(agent.name):
            raise ValueError("Built-in agents cannot be updated")

        from src.infrastructure.adapters.secondary.persistence.models import (
            AgentDefinitionModel,
        )

        result = await self._session.execute(
            select(AgentDefinitionModel).where(AgentDefinitionModel.id == agent.id)
        )
        db_agent = result.scalar_one_or_none()

        if not db_agent:
            raise ValueError(f"Agent not found: {agent.id}")

        db_agent.name = agent.name
        db_agent.display_name = agent.display_name
        db_agent.system_prompt = agent.system_prompt
        db_agent.trigger_description = agent.trigger.description
        db_agent.trigger_examples = list(agent.trigger.examples)
        db_agent.trigger_keywords = list(agent.trigger.keywords)
        db_agent.model = agent.model.value
        db_agent.persona_files = list(agent.persona_files)
        db_agent.allowed_tools = list(agent.allowed_tools)
        db_agent.allowed_skills = list(agent.allowed_skills)
        db_agent.allowed_mcp_servers = list(agent.allowed_mcp_servers)
        db_agent.max_tokens = agent.max_tokens
        db_agent.temperature = agent.temperature
        db_agent.max_iterations = agent.max_iterations
        db_agent.workspace_dir = agent.workspace_dir
        db_agent.workspace_config = agent.workspace_config.to_dict()
        db_agent.can_spawn = agent.can_spawn
        db_agent.max_spawn_depth = agent.max_spawn_depth
        db_agent.agent_to_agent_enabled = agent.agent_to_agent_enabled
        db_agent.agent_to_agent_allowlist = agent.agent_to_agent_allowlist
        db_agent.discoverable = agent.discoverable
        db_agent.source = (
            agent.source.value if isinstance(agent.source, AgentSource) else agent.source
        )
        db_agent.enabled = agent.enabled
        db_agent.max_retries = agent.max_retries
        db_agent.fallback_models = list(agent.fallback_models)
        db_agent.total_invocations = agent.total_invocations
        db_agent.avg_execution_time_ms = agent.avg_execution_time_ms
        db_agent.success_rate = agent.success_rate
        db_agent.metadata_json = agent.metadata
        db_agent.session_policy = agent.session_policy.to_dict() if agent.session_policy else None
        db_agent.delegate_config = (
            agent.delegate_config.to_dict() if agent.delegate_config else None
        )
        db_agent.updated_at = agent.updated_at

        await self._session.flush()

        return agent

    async def delete(self, agent_id: str) -> bool:
        if is_builtin_agent_id(agent_id):
            raise ValueError("Built-in agents cannot be deleted")

        from src.infrastructure.adapters.secondary.persistence.models import (
            AgentDefinitionModel,
        )

        result = await self._session.execute(
            delete(AgentDefinitionModel).where(AgentDefinitionModel.id == agent_id)
        )

        if cast(CursorResult[Any], result).rowcount == 0:
            raise ValueError(f"Agent not found: {agent_id}")
        return True

    async def list_by_tenant(
        self,
        tenant_id: str,
        enabled_only: bool = False,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Agent]:
        from src.infrastructure.adapters.secondary.persistence.models import (
            AgentDefinitionModel,
        )

        query = select(AgentDefinitionModel).where(AgentDefinitionModel.tenant_id == tenant_id)

        if enabled_only:
            query = query.where(AgentDefinitionModel.enabled.is_(True))

        builtin_agents = list_builtin_agents(tenant_id=tenant_id)
        builtin_slice = builtin_agents[offset : offset + limit]
        builtin_count = len(builtin_slice)

        db_limit = max(limit - builtin_count, 0)
        db_offset = max(offset - len(builtin_agents), 0)
        query = query.order_by(AgentDefinitionModel.created_at.desc()).limit(db_limit).offset(db_offset)

        result = await self._session.execute(query)
        db_agents = result.scalars().all()

        agents = [d for a in db_agents if (d := self._to_domain(a)) is not None]
        return _dedupe_agents_by_name_prefer_builtin(builtin_slice + agents)

    async def list_by_project(
        self,
        project_id: str,
        tenant_id: str | None = None,
        enabled_only: bool = False,
    ) -> list[Agent]:
        from src.infrastructure.adapters.secondary.persistence.models import (
            AgentDefinitionModel,
        )

        if tenant_id:
            query = select(AgentDefinitionModel).where(
                or_(
                    AgentDefinitionModel.project_id == project_id,
                    (AgentDefinitionModel.project_id.is_(None))
                    & (AgentDefinitionModel.tenant_id == tenant_id),
                )
            )
        else:
            query = select(AgentDefinitionModel).where(
                or_(
                    AgentDefinitionModel.project_id == project_id,
                    AgentDefinitionModel.project_id.is_(None),
                )
            )

        if enabled_only:
            query = query.where(AgentDefinitionModel.enabled.is_(True))

        query = query.order_by(AgentDefinitionModel.created_at.desc())

        result = await self._session.execute(query)
        db_agents = result.scalars().all()

        resolved_tenant_id = tenant_id or BUILTIN_AGENT_NAMESPACE
        agents = [d for a in db_agents if (d := self._to_domain(a)) is not None]
        builtin_agents = list_builtin_agents(
            tenant_id=resolved_tenant_id,
            project_id=project_id,
        )
        return _dedupe_agents_by_name_prefer_builtin(builtin_agents + agents)

    async def set_enabled(
        self,
        agent_id: str,
        enabled: bool,
    ) -> Agent:
        if is_builtin_agent_id(agent_id):
            raise ValueError("Built-in agents cannot be disabled")

        from src.infrastructure.adapters.secondary.persistence.models import (
            AgentDefinitionModel,
        )

        result = await self._session.execute(
            select(AgentDefinitionModel).where(AgentDefinitionModel.id == agent_id)
        )
        db_agent = result.scalar_one_or_none()

        if not db_agent:
            raise ValueError(f"Agent not found: {agent_id}")

        db_agent.enabled = enabled
        db_agent.updated_at = datetime.now(UTC)

        await self._session.flush()

        domain = self._to_domain(db_agent)
        assert domain is not None
        return domain

    async def update_statistics(
        self,
        agent_id: str,
        execution_time_ms: float,
        success: bool,
    ) -> Agent:
        agent = await self.get_by_id(agent_id)
        if not agent:
            raise ValueError(f"Agent not found: {agent_id}")

        updated_agent = agent.record_execution(execution_time_ms, success)
        return await self.update(updated_agent)

    async def count_by_tenant(
        self,
        tenant_id: str,
        enabled_only: bool = False,
    ) -> int:
        from src.infrastructure.adapters.secondary.persistence.models import (
            AgentDefinitionModel,
        )

        query = select(func.count(AgentDefinitionModel.id)).where(
            AgentDefinitionModel.tenant_id == tenant_id
        )

        if enabled_only:
            query = query.where(AgentDefinitionModel.enabled.is_(True))

        result = await self._session.execute(query)
        builtin_count = 1
        return (result.scalar() or 0) + builtin_count

    def _to_domain(self, db_agent: AgentDefinitionModel | None) -> Agent | None:
        if db_agent is None:
            return None

        trigger = AgentTrigger(
            description=db_agent.trigger_description or "",
            examples=list(db_agent.trigger_examples or []),
            keywords=list(db_agent.trigger_keywords or []),
        )

        ws_data = db_agent.workspace_config
        workspace_config = (
            WorkspaceConfig.from_dict(ws_data) if isinstance(ws_data, dict) else WorkspaceConfig()
        )

        sp_data = db_agent.session_policy
        session_policy = SessionPolicy.from_dict(sp_data) if isinstance(sp_data, dict) else None

        dc_data = db_agent.delegate_config
        delegate_config = DelegateConfig.from_dict(dc_data) if isinstance(dc_data, dict) else None

        return Agent(
            id=db_agent.id,
            tenant_id=db_agent.tenant_id,
            project_id=db_agent.project_id,
            name=db_agent.name,
            display_name=db_agent.display_name,
            system_prompt=db_agent.system_prompt,
            trigger=trigger,
            persona_files=list(db_agent.persona_files or []),
            model=AgentModel(db_agent.model),
            temperature=db_agent.temperature,
            max_tokens=db_agent.max_tokens,
            max_iterations=db_agent.max_iterations,
            allowed_tools=list(db_agent.allowed_tools or ["*"]),
            allowed_skills=list(db_agent.allowed_skills or []),
            allowed_mcp_servers=list(db_agent.allowed_mcp_servers or []),
            workspace_dir=db_agent.workspace_dir,
            workspace_config=workspace_config,
            can_spawn=db_agent.can_spawn,
            max_spawn_depth=db_agent.max_spawn_depth,
            agent_to_agent_enabled=(db_agent.agent_to_agent_enabled),
            agent_to_agent_allowlist=db_agent.agent_to_agent_allowlist,
            discoverable=db_agent.discoverable,
            source=AgentSource(db_agent.source),
            enabled=db_agent.enabled,
            max_retries=db_agent.max_retries,
            fallback_models=list(db_agent.fallback_models or []),
            total_invocations=db_agent.total_invocations,
            avg_execution_time_ms=(db_agent.avg_execution_time_ms),
            success_rate=db_agent.success_rate,
            created_at=db_agent.created_at,
            updated_at=(db_agent.updated_at or db_agent.created_at),
            metadata=db_agent.metadata_json,
            session_policy=session_policy,
            delegate_config=delegate_config,
        )
