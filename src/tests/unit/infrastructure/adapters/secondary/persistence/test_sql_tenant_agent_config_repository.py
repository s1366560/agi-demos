"""
Tests for V2 SqlTenantAgentConfigRepository using BaseRepository.
"""

from datetime import datetime, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.agent.tenant_agent_config import ConfigType, TenantAgentConfig
from src.infrastructure.adapters.secondary.persistence.sql_tenant_agent_config_repository import (
    SqlTenantAgentConfigRepository,
)


@pytest.fixture
async def v2_config_repo(v2_db_session: AsyncSession) -> SqlTenantAgentConfigRepository:
    """Create a V2 tenant agent config repository for testing."""
    return SqlTenantAgentConfigRepository(v2_db_session)


class TestSqlTenantAgentConfigRepositoryCreate:
    """Tests for creating configurations."""

    @pytest.mark.asyncio
    async def test_save_new_config(self, v2_config_repo: SqlTenantAgentConfigRepository):
        """Test saving a new configuration."""
        config = TenantAgentConfig(
            id="config-test-1",
            tenant_id="tenant-1",
            config_type=ConfigType.CUSTOM,
            llm_model="gpt-4",
            llm_temperature=0.5,
            pattern_learning_enabled=False,
            multi_level_thinking_enabled=True,
            max_work_plan_steps=15,
            tool_timeout_seconds=60,
            enabled_tools=["search", "calculate"],
            disabled_tools=["danger"],
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        result = await v2_config_repo.save(config)

        assert result.id == "config-test-1"
        assert result.tenant_id == "tenant-1"

    @pytest.mark.asyncio
    async def test_save_updates_existing(self, v2_config_repo: SqlTenantAgentConfigRepository):
        """Test saving updates an existing configuration."""
        config = TenantAgentConfig(
            id="config-update-1",
            tenant_id="tenant-1",
            config_type=ConfigType.CUSTOM,
            llm_model="gpt-4",
            llm_temperature=0.7,
            pattern_learning_enabled=True,
            multi_level_thinking_enabled=True,
            max_work_plan_steps=10,
            tool_timeout_seconds=30,
            enabled_tools=[],
            disabled_tools=[],
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        await v2_config_repo.save(config)

        # Update
        config.llm_model = "gpt-3.5"
        config.llm_temperature = 0.5
        config.updated_at = datetime.now(timezone.utc)

        result = await v2_config_repo.save(config)
        assert result.llm_model == "gpt-3.5"


class TestSqlTenantAgentConfigRepositoryFind:
    """Tests for finding configurations."""

    @pytest.mark.asyncio
    async def test_get_by_tenant_existing(self, v2_config_repo: SqlTenantAgentConfigRepository):
        """Test getting config for a tenant that exists."""
        config = TenantAgentConfig(
            id="config-find-1",
            tenant_id="tenant-find",
            config_type=ConfigType.CUSTOM,
            llm_model="gpt-4",
            llm_temperature=0.7,
            pattern_learning_enabled=True,
            multi_level_thinking_enabled=True,
            max_work_plan_steps=10,
            tool_timeout_seconds=30,
            enabled_tools=[],
            disabled_tools=[],
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        await v2_config_repo.save(config)

        result = await v2_config_repo.get_by_tenant("tenant-find")
        assert result is not None
        assert result.tenant_id == "tenant-find"
        assert result.llm_model == "gpt-4"

    @pytest.mark.asyncio
    async def test_get_by_tenant_not_found(self, v2_config_repo: SqlTenantAgentConfigRepository):
        """Test getting config for a tenant that doesn't exist returns None."""
        result = await v2_config_repo.get_by_tenant("non-existent")
        assert result is None


class TestSqlTenantAgentConfigRepositoryDelete:
    """Tests for deleting configurations."""

    @pytest.mark.asyncio
    async def test_delete_existing(self, v2_config_repo: SqlTenantAgentConfigRepository):
        """Test deleting an existing configuration."""
        config = TenantAgentConfig(
            id="config-delete-1",
            tenant_id="tenant-delete",
            config_type=ConfigType.CUSTOM,
            llm_model="gpt-4",
            llm_temperature=0.7,
            pattern_learning_enabled=True,
            multi_level_thinking_enabled=True,
            max_work_plan_steps=10,
            tool_timeout_seconds=30,
            enabled_tools=[],
            disabled_tools=[],
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        await v2_config_repo.save(config)

        await v2_config_repo.delete("tenant-delete")

        result = await v2_config_repo.get_by_tenant("tenant-delete")
        assert result is None

    @pytest.mark.asyncio
    async def test_delete_nonexistent_raises_error(self, v2_config_repo: SqlTenantAgentConfigRepository):
        """Test deleting a non-existent config raises ValueError."""
        with pytest.raises(ValueError):
            await v2_config_repo.delete("non-existent")


class TestSqlTenantAgentConfigRepositoryExists:
    """Tests for exists method."""

    @pytest.mark.asyncio
    async def test_exists_true(self, v2_config_repo: SqlTenantAgentConfigRepository):
        """Test exists returns True for existing config."""
        config = TenantAgentConfig(
            id="config-exists-1",
            tenant_id="tenant-exists",
            config_type=ConfigType.CUSTOM,
            llm_model="gpt-4",
            llm_temperature=0.7,
            pattern_learning_enabled=True,
            multi_level_thinking_enabled=True,
            max_work_plan_steps=10,
            tool_timeout_seconds=30,
            enabled_tools=[],
            disabled_tools=[],
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        await v2_config_repo.save(config)

        assert await v2_config_repo.exists("tenant-exists") is True

    @pytest.mark.asyncio
    async def test_exists_false(self, v2_config_repo: SqlTenantAgentConfigRepository):
        """Test exists returns False for non-existent config."""
        assert await v2_config_repo.exists("non-existent") is False


class TestSqlTenantAgentConfigRepositoryToDomain:
    """Tests for _to_domain conversion."""

    def test_to_domain_with_none(self, v2_config_repo: SqlTenantAgentConfigRepository):
        """Test that _to_domain handles None input."""
        result = v2_config_repo._to_domain(None)
        assert result is None
