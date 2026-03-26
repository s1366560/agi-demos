"""Tests for SqlWorkspaceAgentRepository."""

from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.workspace.workspace_agent import WorkspaceAgent
from src.infrastructure.adapters.secondary.persistence.sql_workspace_agent_repository import (
    SqlWorkspaceAgentRepository,
)


@pytest.fixture
async def v2_workspace_agent_repo(
    v2_db_session: AsyncSession,
    workspace_test_seed: dict[str, str],
) -> SqlWorkspaceAgentRepository:
    """Create a SqlWorkspaceAgentRepository for testing."""
    return SqlWorkspaceAgentRepository(v2_db_session)


def make_workspace_agent(
    relation_id: str,
    workspace_id: str = "workspace-1",
    agent_id: str = "agent-1",
    is_active: bool = True,
) -> WorkspaceAgent:
    return WorkspaceAgent(
        id=relation_id,
        workspace_id=workspace_id,
        agent_id=agent_id,
        display_name="Agent Display",
        description="Agent relation",
        config={"mode": "assist"},
        is_active=is_active,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


class TestSqlWorkspaceAgentRepository:
    """Tests for workspace-agent repository behavior."""

    @pytest.mark.asyncio
    async def test_save_and_find_by_id(self, v2_workspace_agent_repo: SqlWorkspaceAgentRepository) -> None:
        relation = make_workspace_agent("wa-1")
        await v2_workspace_agent_repo.save(relation)

        found = await v2_workspace_agent_repo.find_by_id("wa-1")
        assert found is not None
        assert found.id == "wa-1"
        assert found.workspace_id == "workspace-1"
        assert found.agent_id == "agent-1"

    @pytest.mark.asyncio
    async def test_find_by_workspace_with_active_filter(
        self, v2_workspace_agent_repo: SqlWorkspaceAgentRepository
    ) -> None:
        await v2_workspace_agent_repo.save(
            make_workspace_agent("wa-a", workspace_id="workspace-a", agent_id="agent-a", is_active=True)
        )
        await v2_workspace_agent_repo.save(
            make_workspace_agent("wa-b", workspace_id="workspace-a", agent_id="agent-b", is_active=False)
        )

        all_items = await v2_workspace_agent_repo.find_by_workspace("workspace-a", active_only=False)
        assert len(all_items) == 2

        active_items = await v2_workspace_agent_repo.find_by_workspace("workspace-a", active_only=True)
        assert len(active_items) == 1
        assert active_items[0].agent_id == "agent-a"

    @pytest.mark.asyncio
    async def test_save_updates_existing_relation(
        self, v2_workspace_agent_repo: SqlWorkspaceAgentRepository
    ) -> None:
        await v2_workspace_agent_repo.save(make_workspace_agent("wa-upd", is_active=True))
        updated = make_workspace_agent("wa-upd", is_active=False)
        updated.display_name = "Updated Name"
        await v2_workspace_agent_repo.save(updated)

        found = await v2_workspace_agent_repo.find_by_id("wa-upd")
        assert found is not None
        assert found.is_active is False
        assert found.display_name == "Updated Name"

    @pytest.mark.asyncio
    async def test_delete_relation(self, v2_workspace_agent_repo: SqlWorkspaceAgentRepository) -> None:
        await v2_workspace_agent_repo.save(make_workspace_agent("wa-del"))

        deleted = await v2_workspace_agent_repo.delete("wa-del")
        assert deleted is True
        assert await v2_workspace_agent_repo.find_by_id("wa-del") is None
