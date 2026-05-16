"""Unit tests for SqlAgentRegistryRepository built-in agent behavior."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.domain.model.agent.agent_source import AgentSource
from src.infrastructure.adapters.secondary.persistence.models import AgentDefinitionModel
from src.infrastructure.adapters.secondary.persistence.sql_agent_registry import (
    SqlAgentRegistryRepository,
)
from src.infrastructure.agent.sisyphus.builtin_agent import (
    build_builtin_sisyphus_agent,
    list_builtin_agents,
)


def _build_custom_agent(agent_id: str, name: str, tenant_id: str):
    """Create a mutable custom agent from the builtin template."""
    agent = build_builtin_sisyphus_agent(tenant_id=tenant_id)
    agent.id = agent_id
    agent.name = name
    agent.display_name = name.title()
    agent.source = AgentSource.DATABASE
    return agent


def _make_repo() -> SqlAgentRegistryRepository:
    session = MagicMock()
    session.execute = AsyncMock()
    return SqlAgentRegistryRepository(session)


@pytest.mark.unit
class TestSqlAgentRegistryRepository:
    """Focused tests for built-in ID resolution and pagination behavior."""

    @pytest.mark.asyncio
    async def test_get_by_id_resolves_builtin_for_requested_tenant(self) -> None:
        repo = _make_repo()

        agent = await repo.get_by_id("builtin:sisyphus", tenant_id="tenant-1", project_id="proj-1")

        assert agent is not None
        assert agent.tenant_id == "tenant-1"
        assert agent.project_id == "proj-1"

    @pytest.mark.asyncio
    async def test_update_rejects_reserved_builtin_name(self) -> None:
        repo = _make_repo()
        agent = _build_custom_agent("custom-agent", "sisyphus", "tenant-1")

        with pytest.raises(ValueError, match="Built-in agents cannot be updated"):
            await repo.update(agent)

    @pytest.mark.asyncio
    async def test_list_by_tenant_includes_builtin_only_on_first_page(self) -> None:
        repo = _make_repo()
        repo._to_domain = MagicMock(  # type: ignore[method-assign]
            side_effect=[
                _build_custom_agent("custom-1", "custom-one", "tenant-1"),
                _build_custom_agent("custom-2", "custom-two", "tenant-1"),
            ]
        )
        builtin_ids = [agent.id for agent in list_builtin_agents(tenant_id="tenant-1")]

        result = MagicMock()
        result.scalars.return_value.all.return_value = ["row-1", "row-2"]
        repo._session.execute.return_value = result

        first_page = await repo.list_by_tenant("tenant-1", limit=2, offset=0)
        database_page = await repo.list_by_tenant("tenant-1", limit=2, offset=len(builtin_ids))

        assert [agent.id for agent in first_page] == builtin_ids[:2]
        assert [agent.id for agent in database_page] == ["custom-1", "custom-2"]

    @pytest.mark.asyncio
    async def test_list_by_project_prefers_builtin_when_legacy_db_name_collides(self) -> None:
        repo = _make_repo()
        repo._to_domain = MagicMock(  # type: ignore[method-assign]
            side_effect=[
                _build_custom_agent("custom-sisyphus", "sisyphus", "tenant-1"),
                _build_custom_agent("custom-1", "custom-one", "tenant-1"),
            ]
        )
        result = MagicMock()
        result.scalars.return_value.all.return_value = ["row-1", "row-2"]
        repo._session.execute.return_value = result

        agents = await repo.list_by_project("proj-1", tenant_id="tenant-1")

        builtin_ids = [
            agent.id
            for agent in list_builtin_agents(tenant_id="tenant-1", project_id="proj-1")
        ]
        assert [agent.id for agent in agents] == [*builtin_ids, "custom-1"]

    @pytest.mark.asyncio
    async def test_get_by_id_refreshes_existing_identity_map_rows(
        self,
        db_session: AsyncSession,
        test_tenant_db,
        test_project_db,
    ) -> None:
        agent_id = "agent-refresh-test"
        db_session.add(
            AgentDefinitionModel(
                id=agent_id,
                tenant_id=test_tenant_db.id,
                project_id=test_project_db.id,
                name="refresh-test-agent",
                display_name="Refresh Test Agent",
                system_prompt="You are a refresh test agent.",
                trigger_description="Refresh test trigger",
                allowed_tools=[],
                allowed_skills=[],
                allowed_mcp_servers=[],
                source="database",
                max_iterations=10,
            )
        )
        await db_session.commit()

        repo = SqlAgentRegistryRepository(db_session)
        first = await repo.get_by_id(
            agent_id,
            tenant_id=test_tenant_db.id,
            project_id=test_project_db.id,
        )
        assert first is not None
        assert first.max_iterations == 10

        session_factory = async_sessionmaker(
            db_session.bind,
            class_=AsyncSession,
            expire_on_commit=False,
        )
        async with session_factory() as other_session:
            row = await other_session.get(AgentDefinitionModel, agent_id)
            assert row is not None
            row.max_iterations = 42
            await other_session.commit()

        refreshed = await repo.get_by_id(
            agent_id,
            tenant_id=test_tenant_db.id,
            project_id=test_project_db.id,
        )
        assert refreshed is not None
        assert refreshed.max_iterations == 42
