"""
Tests for V2 SqlToolEnvironmentVariableRepository using BaseRepository.
"""

from datetime import datetime, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.agent.tool_environment_variable import (
    EnvVarScope,
    ToolEnvironmentVariable,
)
from src.infrastructure.adapters.secondary.persistence.v2_sql_tool_environment_variable_repository import (
    V2SqlToolEnvironmentVariableRepository,
)


@pytest.fixture
async def v2_env_var_repo(v2_db_session: AsyncSession) -> V2SqlToolEnvironmentVariableRepository:
    """Create a V2 tool environment variable repository for testing."""
    return V2SqlToolEnvironmentVariableRepository(v2_db_session)


def make_env_var(
    env_var_id: str,
    tenant_id: str,
    tool_name: str,
    variable_name: str,
) -> ToolEnvironmentVariable:
    """Factory for creating ToolEnvironmentVariable objects."""
    return ToolEnvironmentVariable(
        id=env_var_id,
        tenant_id=tenant_id,
        project_id=None,
        tool_name=tool_name,
        variable_name=variable_name,
        encrypted_value="encrypted_value",
        description=f"Description for {variable_name}",
        is_required=False,
        is_secret=True,
        scope=EnvVarScope.TENANT,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )


class TestV2SqlToolEnvironmentVariableRepositoryCreate:
    """Tests for creating environment variables."""

    @pytest.mark.asyncio
    async def test_create_new_env_var(self, v2_env_var_repo: V2SqlToolEnvironmentVariableRepository):
        """Test creating a new environment variable."""
        env_var = make_env_var("env-1", "tenant-1", "search", "API_KEY")

        result = await v2_env_var_repo.create(env_var)

        assert result.id == "env-1"
        assert result.tool_name == "search"
        assert result.variable_name == "API_KEY"


class TestV2SqlToolEnvironmentVariableRepositoryFind:
    """Tests for finding environment variables."""

    @pytest.mark.asyncio
    async def test_get_by_id_existing(self, v2_env_var_repo: V2SqlToolEnvironmentVariableRepository):
        """Test getting an environment variable by ID."""
        env_var = make_env_var("env-find-1", "tenant-1", "search", "API_KEY")
        await v2_env_var_repo.create(env_var)

        result = await v2_env_var_repo.get_by_id("env-find-1")
        assert result is not None
        assert result.variable_name == "API_KEY"

    @pytest.mark.asyncio
    async def test_get_by_id_not_found(self, v2_env_var_repo: V2SqlToolEnvironmentVariableRepository):
        """Test getting a non-existent environment variable returns None."""
        result = await v2_env_var_repo.get_by_id("non-existent")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_tenant_level(self, v2_env_var_repo: V2SqlToolEnvironmentVariableRepository):
        """Test getting a tenant-level environment variable."""
        env_var = make_env_var("env-tenant-1", "tenant-1", "search", "API_KEY")
        await v2_env_var_repo.create(env_var)

        result = await v2_env_var_repo.get("tenant-1", "search", "API_KEY")
        assert result is not None
        assert result.scope == EnvVarScope.TENANT

    @pytest.mark.asyncio
    async def test_get_for_tool(self, v2_env_var_repo: V2SqlToolEnvironmentVariableRepository):
        """Test getting all environment variables for a tool."""
        env_var1 = make_env_var("env-tool-1", "tenant-1", "search", "API_KEY")
        env_var2 = make_env_var("env-tool-2", "tenant-1", "search", "ENDPOINT")
        await v2_env_var_repo.create(env_var1)
        await v2_env_var_repo.create(env_var2)

        results = await v2_env_var_repo.get_for_tool("tenant-1", "search")
        assert len(results) == 2


class TestV2SqlToolEnvironmentVariableRepositoryUpdate:
    """Tests for updating environment variables."""

    @pytest.mark.asyncio
    async def test_update_existing(self, v2_env_var_repo: V2SqlToolEnvironmentVariableRepository):
        """Test updating an existing environment variable."""
        env_var = make_env_var("env-update-1", "tenant-1", "search", "API_KEY")
        await v2_env_var_repo.create(env_var)

        env_var.encrypted_value = "new_encrypted_value"
        env_var.description = "Updated description"

        result = await v2_env_var_repo.update(env_var)
        assert result.encrypted_value == "new_encrypted_value"

    @pytest.mark.asyncio
    async def test_update_nonexistent_raises_error(self, v2_env_var_repo: V2SqlToolEnvironmentVariableRepository):
        """Test updating a non-existent environment variable raises ValueError."""
        env_var = make_env_var("non-existent", "tenant-1", "search", "API_KEY")

        with pytest.raises(ValueError):
            await v2_env_var_repo.update(env_var)


class TestV2SqlToolEnvironmentVariableRepositoryDelete:
    """Tests for deleting environment variables."""

    @pytest.mark.asyncio
    async def test_delete_existing(self, v2_env_var_repo: V2SqlToolEnvironmentVariableRepository):
        """Test deleting an existing environment variable."""
        env_var = make_env_var("env-delete-1", "tenant-1", "search", "API_KEY")
        await v2_env_var_repo.create(env_var)

        await v2_env_var_repo.delete("env-delete-1")

        result = await v2_env_var_repo.get_by_id("env-delete-1")
        assert result is None

    @pytest.mark.asyncio
    async def test_delete_nonexistent_raises_error(self, v2_env_var_repo: V2SqlToolEnvironmentVariableRepository):
        """Test deleting a non-existent environment variable raises ValueError."""
        with pytest.raises(ValueError):
            await v2_env_var_repo.delete("non-existent")


class TestV2SqlToolEnvironmentVariableRepositoryUpsert:
    """Tests for upsert operations."""

    @pytest.mark.asyncio
    async def test_upsert_create(self, v2_env_var_repo: V2SqlToolEnvironmentVariableRepository):
        """Test upsert creates new variable when it doesn't exist."""
        env_var = make_env_var("env-upsert-create-1", "tenant-1", "search", "NEW_VAR")

        result = await v2_env_var_repo.upsert(env_var)
        assert result.id == "env-upsert-create-1"

    @pytest.mark.asyncio
    async def test_upsert_update(self, v2_env_var_repo: V2SqlToolEnvironmentVariableRepository):
        """Test upsert updates existing variable."""
        env_var = make_env_var("env-upsert-update-1", "tenant-1", "search", "UPDATE_VAR")
        await v2_env_var_repo.create(env_var)

        env_var.encrypted_value = "updated_value"
        result = await v2_env_var_repo.upsert(env_var)
        assert result.encrypted_value == "updated_value"


class TestV2SqlToolEnvironmentVariableRepositoryList:
    """Tests for listing environment variables."""

    @pytest.mark.asyncio
    async def test_list_by_tenant(self, v2_env_var_repo: V2SqlToolEnvironmentVariableRepository):
        """Test listing environment variables by tenant."""
        for i in range(3):
            env_var = make_env_var(f"env-list-{i}", "tenant-list-1", f"tool-{i}", f"VAR-{i}")
            await v2_env_var_repo.create(env_var)

        results = await v2_env_var_repo.list_by_tenant("tenant-list-1")
        assert len(results) == 3

    @pytest.mark.asyncio
    async def test_list_by_tenant_with_scope(self, v2_env_var_repo: V2SqlToolEnvironmentVariableRepository):
        """Test listing environment variables by tenant and scope."""
        env_var1 = make_env_var("env-scope-1", "tenant-scope-1", "tool1", "VAR1")
        env_var1.scope = EnvVarScope.TENANT
        await v2_env_var_repo.create(env_var1)

        env_var2 = make_env_var("env-scope-2", "tenant-scope-1", "tool2", "VAR2")
        env_var2.scope = EnvVarScope.PROJECT
        await v2_env_var_repo.create(env_var2)

        results = await v2_env_var_repo.list_by_tenant("tenant-scope-1", EnvVarScope.TENANT)
        assert len(results) == 1
        assert results[0].scope == EnvVarScope.TENANT
