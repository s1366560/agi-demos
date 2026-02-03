"""
Tests for V2 SqlTenantSkillConfigRepository using BaseRepository.
"""

from datetime import datetime, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.agent.tenant_skill_config import (
    TenantSkillAction,
    TenantSkillConfig,
)
from src.infrastructure.adapters.secondary.persistence.v2_sql_tenant_skill_config_repository import (
    V2SqlTenantSkillConfigRepository,
)


@pytest.fixture
async def v2_skill_config_repo(v2_db_session: AsyncSession) -> V2SqlTenantSkillConfigRepository:
    """Create a V2 tenant skill config repository for testing."""
    return V2SqlTenantSkillConfigRepository(v2_db_session)


class TestV2SqlTenantSkillConfigRepositoryCreate:
    """Tests for creating skill configs."""

    @pytest.mark.asyncio
    async def test_create_new_config(self, v2_skill_config_repo: V2SqlTenantSkillConfigRepository):
        """Test creating a new tenant skill config."""
        config = TenantSkillConfig(
            id="config-test-1",
            tenant_id="tenant-1",
            system_skill_name="test_skill",
            action=TenantSkillAction.DISABLE,
            override_skill_id=None,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        result = await v2_skill_config_repo.create(config)

        assert result.id == "config-test-1"
        assert result.tenant_id == "tenant-1"


class TestV2SqlTenantSkillConfigRepositoryFind:
    """Tests for finding skill configs."""

    @pytest.mark.asyncio
    async def test_get_by_id_existing(self, v2_skill_config_repo: V2SqlTenantSkillConfigRepository):
        """Test getting a config by ID."""
        config = TenantSkillConfig(
            id="config-find-1",
            tenant_id="tenant-1",
            system_skill_name="find_skill",
            action=TenantSkillAction.DISABLE,
            override_skill_id=None,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        await v2_skill_config_repo.create(config)

        result = await v2_skill_config_repo.get_by_id("config-find-1")
        assert result is not None
        assert result.system_skill_name == "find_skill"

    @pytest.mark.asyncio
    async def test_get_by_id_not_found(self, v2_skill_config_repo: V2SqlTenantSkillConfigRepository):
        """Test getting a non-existent config returns None."""
        result = await v2_skill_config_repo.get_by_id("non-existent")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_by_tenant_and_skill(self, v2_skill_config_repo: V2SqlTenantSkillConfigRepository):
        """Test getting a config by tenant and skill name."""
        config = TenantSkillConfig(
            id="config-tenant-skill-1",
            tenant_id="tenant-ts",
            system_skill_name="ts_skill",
            action=TenantSkillAction.OVERRIDE,
            override_skill_id="override-1",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        await v2_skill_config_repo.create(config)

        result = await v2_skill_config_repo.get_by_tenant_and_skill("tenant-ts", "ts_skill")
        assert result is not None
        assert result.action == TenantSkillAction.OVERRIDE


class TestV2SqlTenantSkillConfigRepositoryUpdate:
    """Tests for updating skill configs."""

    @pytest.mark.asyncio
    async def test_update_existing_config(self, v2_skill_config_repo: V2SqlTenantSkillConfigRepository):
        """Test updating an existing config."""
        config = TenantSkillConfig(
            id="config-update-1",
            tenant_id="tenant-1",
            system_skill_name="update_skill",
            action=TenantSkillAction.DISABLE,
            override_skill_id=None,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        await v2_skill_config_repo.create(config)

        config.action = TenantSkillAction.OVERRIDE
        config.override_skill_id = "override-1"

        result = await v2_skill_config_repo.update(config)
        assert result.action == TenantSkillAction.OVERRIDE

    @pytest.mark.asyncio
    async def test_update_nonexistent_raises_error(self, v2_skill_config_repo: V2SqlTenantSkillConfigRepository):
        """Test updating a non-existent config raises ValueError."""
        config = TenantSkillConfig(
            id="config-update-nonexist",
            tenant_id="tenant-1",
            system_skill_name="skill",
            action=TenantSkillAction.DISABLE,
            override_skill_id=None,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        with pytest.raises(ValueError):
            await v2_skill_config_repo.update(config)


class TestV2SqlTenantSkillConfigRepositoryDelete:
    """Tests for deleting skill configs."""

    @pytest.mark.asyncio
    async def test_delete_existing(self, v2_skill_config_repo: V2SqlTenantSkillConfigRepository):
        """Test deleting an existing config."""
        config = TenantSkillConfig(
            id="config-delete-1",
            tenant_id="tenant-1",
            system_skill_name="delete_skill",
            action=TenantSkillAction.DISABLE,
            override_skill_id=None,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        await v2_skill_config_repo.create(config)

        await v2_skill_config_repo.delete("config-delete-1")

        result = await v2_skill_config_repo.get_by_id("config-delete-1")
        assert result is None

    @pytest.mark.asyncio
    async def test_delete_by_tenant_and_skill(self, v2_skill_config_repo: V2SqlTenantSkillConfigRepository):
        """Test deleting a config by tenant and skill name."""
        config = TenantSkillConfig(
            id="config-del-ts-1",
            tenant_id="tenant-del",
            system_skill_name="del_skill",
            action=TenantSkillAction.DISABLE,
            override_skill_id=None,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        await v2_skill_config_repo.create(config)

        await v2_skill_config_repo.delete_by_tenant_and_skill("tenant-del", "del_skill")

        result = await v2_skill_config_repo.get_by_tenant_and_skill("tenant-del", "del_skill")
        assert result is None


class TestV2SqlTenantSkillConfigRepositoryList:
    """Tests for listing skill configs."""

    @pytest.mark.asyncio
    async def test_list_by_tenant(self, v2_skill_config_repo: V2SqlTenantSkillConfigRepository):
        """Test listing all configs for a tenant."""
        for i in range(3):
            config = TenantSkillConfig(
                id=f"config-list-{i}",
                tenant_id="tenant-list",
                system_skill_name=f"skill-{i}",
                action=TenantSkillAction.DISABLE,
                override_skill_id=None,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
            await v2_skill_config_repo.create(config)

        configs = await v2_skill_config_repo.list_by_tenant("tenant-list")
        assert len(configs) == 3

    @pytest.mark.asyncio
    async def test_get_configs_map(self, v2_skill_config_repo: V2SqlTenantSkillConfigRepository):
        """Test getting configs as a map."""
        config1 = TenantSkillConfig(
            id="config-map-1",
            tenant_id="tenant-map",
            system_skill_name="skill1",
            action=TenantSkillAction.DISABLE,
            override_skill_id=None,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        config2 = TenantSkillConfig(
            id="config-map-2",
            tenant_id="tenant-map",
            system_skill_name="skill2",
            action=TenantSkillAction.OVERRIDE,
            override_skill_id="override-1",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        await v2_skill_config_repo.create(config1)
        await v2_skill_config_repo.create(config2)

        configs_map = await v2_skill_config_repo.get_configs_map("tenant-map")
        assert "skill1" in configs_map
        assert "skill2" in configs_map
        assert configs_map["skill1"].action == TenantSkillAction.DISABLE

    @pytest.mark.asyncio
    async def test_count_by_tenant(self, v2_skill_config_repo: V2SqlTenantSkillConfigRepository):
        """Test counting configs for a tenant."""
        for i in range(3):
            config = TenantSkillConfig(
                id=f"config-count-{i}",
                tenant_id="tenant-count",
                system_skill_name=f"skill-{i}",
                action=TenantSkillAction.DISABLE,
                override_skill_id=None,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
            await v2_skill_config_repo.create(config)

        count = await v2_skill_config_repo.count_by_tenant("tenant-count")
        assert count == 3


class TestV2SqlTenantSkillConfigRepositoryToDomain:
    """Tests for _to_domain conversion."""

    def test_to_domain_with_none(self, v2_skill_config_repo: V2SqlTenantSkillConfigRepository):
        """Test that _to_domain returns None for None input."""
        result = v2_skill_config_repo._to_domain(None)
        assert result is None
