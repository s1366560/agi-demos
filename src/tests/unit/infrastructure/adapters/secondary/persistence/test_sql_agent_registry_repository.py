"""Unit tests for SqlAgentRegistryRepository built-in agent behavior."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.domain.model.agent.agent_source import AgentSource
from src.infrastructure.adapters.secondary.persistence.sql_agent_registry import (
    SqlAgentRegistryRepository,
)
from src.infrastructure.agent.sisyphus.builtin_agent import build_builtin_sisyphus_agent


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
                _build_custom_agent("custom-1", "custom-one", "tenant-1"),
                _build_custom_agent("custom-2", "custom-two", "tenant-1"),
            ]
        )

        first_result = MagicMock()
        first_result.scalars.return_value.all.return_value = ["row-1"]
        second_result = MagicMock()
        second_result.scalars.return_value.all.return_value = ["row-1", "row-2"]
        repo._session.execute.side_effect = [first_result, second_result]

        first_page = await repo.list_by_tenant("tenant-1", limit=2, offset=0)
        second_page = await repo.list_by_tenant("tenant-1", limit=2, offset=1)

        assert [agent.id for agent in first_page] == ["builtin:sisyphus", "custom-1"]
        assert [agent.id for agent in second_page] == ["custom-1", "custom-2"]
