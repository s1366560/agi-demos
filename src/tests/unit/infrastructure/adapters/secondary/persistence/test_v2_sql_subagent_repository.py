"""
Tests for V2 SqlSubAgentRepository using BaseRepository.
"""

from datetime import datetime, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.agent.subagent import AgentModel, AgentTrigger, SubAgent
from src.infrastructure.adapters.secondary.persistence.v2_sql_subagent_repository import (
    V2SqlSubAgentRepository,
)


@pytest.fixture
async def v2_subagent_repo(v2_db_session: AsyncSession) -> V2SqlSubAgentRepository:
    """Create a V2 subagent repository for testing."""
    return V2SqlSubAgentRepository(v2_db_session)


def make_subagent(
    subagent_id: str,
    tenant_id: str,
    name: str = "test_subagent",
) -> SubAgent:
    """Factory for creating SubAgent objects."""
    return SubAgent(
        id=subagent_id,
        tenant_id=tenant_id,
        project_id=None,
        name=name,
        display_name="Test SubAgent",
        system_prompt="You are a test subagent",
        trigger=AgentTrigger(
            description="Test trigger",
            examples=["example1", "example2"],
            keywords=["test", "helper"],
        ),
        model=AgentModel.GPT4O,
        color="#FF0000",
        allowed_tools=["*"],
        allowed_skills=[],
        allowed_mcp_servers=[],
        max_tokens=4096,
        temperature=0.7,
        max_iterations=10,
        enabled=True,
        total_invocations=0,
        avg_execution_time_ms=0.0,
        success_rate=1.0,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        metadata={},
    )


class TestV2SqlSubAgentRepositoryCreate:
    """Tests for creating subagents."""

    @pytest.mark.asyncio
    async def test_create_new_subagent(self, v2_subagent_repo: V2SqlSubAgentRepository):
        """Test creating a new subagent."""
        subagent = make_subagent("subagent-test-1", "tenant-1")

        result = await v2_subagent_repo.create(subagent)

        assert result.id == "subagent-test-1"
        assert result.name == "test_subagent"

    @pytest.mark.asyncio
    async def test_create_with_all_fields(self, v2_subagent_repo: V2SqlSubAgentRepository):
        """Test creating a subagent with all fields populated."""
        subagent = make_subagent("subagent-full-1", "tenant-1", "full_subagent")
        subagent.allowed_tools = ["search", "calculate"]
        subagent.allowed_skills = ["web_search"]
        subagent.temperature = 0.5
        subagent.max_iterations = 20

        result = await v2_subagent_repo.create(subagent)

        assert result.allowed_tools == ["search", "calculate"]


class TestV2SqlSubAgentRepositoryFind:
    """Tests for finding subagents."""

    @pytest.mark.asyncio
    async def test_get_by_id_existing(self, v2_subagent_repo: V2SqlSubAgentRepository):
        """Test getting a subagent by ID."""
        subagent = make_subagent("subagent-find-1", "tenant-1", "find_me")
        await v2_subagent_repo.create(subagent)

        result = await v2_subagent_repo.get_by_id("subagent-find-1")
        assert result is not None
        assert result.name == "find_me"

    @pytest.mark.asyncio
    async def test_get_by_id_not_found(self, v2_subagent_repo: V2SqlSubAgentRepository):
        """Test getting a non-existent subagent returns None."""
        result = await v2_subagent_repo.get_by_id("non-existent")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_by_name(self, v2_subagent_repo: V2SqlSubAgentRepository):
        """Test getting a subagent by name within a tenant."""
        subagent = make_subagent("subagent-name-1", "tenant-name-1", "unique_name")
        await v2_subagent_repo.create(subagent)

        result = await v2_subagent_repo.get_by_name("tenant-name-1", "unique_name")
        assert result is not None
        assert result.id == "subagent-name-1"

    @pytest.mark.asyncio
    async def test_list_by_tenant(self, v2_subagent_repo: V2SqlSubAgentRepository):
        """Test listing subagents by tenant ID."""
        for i in range(3):
            subagent = make_subagent(f"subagent-list-{i}", "tenant-list-1", f"subagent-{i}")
            await v2_subagent_repo.create(subagent)

        results = await v2_subagent_repo.list_by_tenant("tenant-list-1")
        assert len(results) == 3

    @pytest.mark.asyncio
    async def test_list_by_tenant_enabled_only(self, v2_subagent_repo: V2SqlSubAgentRepository):
        """Test listing enabled subagents only."""
        subagent1 = make_subagent("subagent-enabled-1", "tenant-filter-1", "enabled_subagent")
        subagent1.enabled = True
        await v2_subagent_repo.create(subagent1)

        subagent2 = make_subagent("subagent-enabled-2", "tenant-filter-1", "disabled_subagent")
        subagent2.enabled = False
        await v2_subagent_repo.create(subagent2)

        results = await v2_subagent_repo.list_by_tenant("tenant-filter-1", enabled_only=True)
        assert len(results) == 1
        assert results[0].enabled is True

    @pytest.mark.asyncio
    async def test_list_by_project(self, v2_subagent_repo: V2SqlSubAgentRepository):
        """Test listing subagents by project ID."""
        subagent1 = make_subagent("subagent-proj-1", "tenant-1", "proj1_subagent")
        subagent1.project_id = "project-1"
        await v2_subagent_repo.create(subagent1)

        subagent2 = make_subagent("subagent-proj-2", "tenant-1", "proj2_subagent")
        subagent2.project_id = "project-2"
        await v2_subagent_repo.create(subagent2)

        results = await v2_subagent_repo.list_by_project("project-1")
        assert len(results) == 1
        assert results[0].project_id == "project-1"


class TestV2SqlSubAgentRepositoryUpdate:
    """Tests for updating subagents."""

    @pytest.mark.asyncio
    async def test_update_existing(self, v2_subagent_repo: V2SqlSubAgentRepository):
        """Test updating an existing subagent."""
        subagent = make_subagent("subagent-update-1", "tenant-1")
        await v2_subagent_repo.create(subagent)

        subagent.display_name = "Updated SubAgent"
        subagent.temperature = 0.9

        result = await v2_subagent_repo.update(subagent)
        assert result.display_name == "Updated SubAgent"
        assert result.temperature == 0.9

    @pytest.mark.asyncio
    async def test_update_nonexistent_raises_error(self, v2_subagent_repo: V2SqlSubAgentRepository):
        """Test updating a non-existent subagent raises ValueError."""
        subagent = make_subagent("non-existent", "tenant-1")

        with pytest.raises(ValueError):
            await v2_subagent_repo.update(subagent)


class TestV2SqlSubAgentRepositoryDelete:
    """Tests for deleting subagents."""

    @pytest.mark.asyncio
    async def test_delete_existing(self, v2_subagent_repo: V2SqlSubAgentRepository):
        """Test deleting an existing subagent."""
        subagent = make_subagent("subagent-delete-1", "tenant-1")
        await v2_subagent_repo.create(subagent)

        await v2_subagent_repo.delete("subagent-delete-1")

        result = await v2_subagent_repo.get_by_id("subagent-delete-1")
        assert result is None

    @pytest.mark.asyncio
    async def test_delete_nonexistent_raises_error(self, v2_subagent_repo: V2SqlSubAgentRepository):
        """Test deleting a non-existent subagent raises ValueError."""
        with pytest.raises(ValueError):
            await v2_subagent_repo.delete("non-existent")


class TestV2SqlSubAgentRepositoryStatistics:
    """Tests for subagent statistics."""

    @pytest.mark.asyncio
    async def test_set_enabled(self, v2_subagent_repo: V2SqlSubAgentRepository):
        """Test enabling/disabling a subagent."""
        subagent = make_subagent("subagent-enable-1", "tenant-1")
        await v2_subagent_repo.create(subagent)

        result = await v2_subagent_repo.set_enabled("subagent-enable-1", False)
        assert result.enabled is False

        result = await v2_subagent_repo.set_enabled("subagent-enable-1", True)
        assert result.enabled is True

    @pytest.mark.asyncio
    async def test_update_statistics(self, v2_subagent_repo: V2SqlSubAgentRepository):
        """Test updating execution statistics."""
        subagent = make_subagent("subagent-stats-1", "tenant-1")
        await v2_subagent_repo.create(subagent)

        result = await v2_subagent_repo.update_statistics("subagent-stats-1", 150.0, True)
        assert result.total_invocations == 1
        assert result.success_rate == 1.0

    @pytest.mark.asyncio
    async def test_count_by_tenant(self, v2_subagent_repo: V2SqlSubAgentRepository):
        """Test counting subagents by tenant."""
        for i in range(3):
            subagent = make_subagent(f"subagent-count-{i}", "tenant-count-1", f"count_subagent_{i}")
            await v2_subagent_repo.create(subagent)

        count = await v2_subagent_repo.count_by_tenant("tenant-count-1")
        assert count == 3


class TestV2SqlSubAgentRepositorySearch:
    """Tests for searching subagents."""

    @pytest.mark.asyncio
    async def test_find_by_keywords(self, v2_subagent_repo: V2SqlSubAgentRepository):
        """Test finding subagents by keyword matching."""
        subagent1 = make_subagent("subagent-keyword-1", "tenant-keyword-1", "search_subagent")
        subagent1.trigger = AgentTrigger(
            description="Search helper",
            examples=["search for things"],
            keywords=["search", "find"],
        )
        await v2_subagent_repo.create(subagent1)

        subagent2 = make_subagent("subagent-keyword-2", "tenant-keyword-1", "calc_subagent")
        subagent2.trigger = AgentTrigger(
            description="Calculate helper",
            examples=["do math"],
            keywords=["calculate", "math"],
        )
        await v2_subagent_repo.create(subagent2)

        results = await v2_subagent_repo.find_by_keywords("tenant-keyword-1", "search")
        assert len(results) == 1
        assert results[0].id == "subagent-keyword-1"
