"""
Tests for V2 SqlMCPServerRepository using BaseRepository.
"""

from datetime import datetime, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.adapters.secondary.persistence.models import Tenant as DBTenant
from src.infrastructure.adapters.secondary.persistence.sql_mcp_server_repository import (
    SqlMCPServerRepository,
)


@pytest.fixture
async def v2_mcp_repo(db_session: AsyncSession, test_tenant_db: DBTenant) -> SqlMCPServerRepository:
    """Create a V2 MCP server repository for testing."""
    return SqlMCPServerRepository(db_session)


@pytest.fixture
async def test_tenant_db(db_session: AsyncSession) -> DBTenant:
    """Create a test tenant in the database."""
    import re

    def _generate_slug(name: str) -> str:
        slug = re.sub(r"[^\w\s-]", "", name.lower())
        slug = re.sub(r"[\s_]+", "-", slug)
        return slug.strip("-")

    tenant = DBTenant(
        id="tenant-test-1",
        name="Test Tenant",
        slug=_generate_slug("Test Tenant"),
        owner_id="user-owner-1",
        description="A test tenant",
    )
    db_session.add(tenant)
    await db_session.flush()
    return tenant


class TestSqlMCPServerRepositoryCreate:
    """Tests for creating MCP servers."""

    @pytest.mark.asyncio
    async def test_create_server(self, v2_mcp_repo: SqlMCPServerRepository):
        """Test creating a new MCP server."""
        server_id = await v2_mcp_repo.create(
            tenant_id="tenant-test-1",
            name="Test Server",
            description="A test MCP server",
            server_type="stdio",
            transport_config={"command": "node", "args": ["server.js"]},
            enabled=True,
        )

        assert server_id is not None
        assert len(server_id) > 0

        # Verify server was created
        server = await v2_mcp_repo.get_by_id(server_id)
        assert server is not None
        assert server["name"] == "Test Server"
        assert server["server_type"] == "stdio"


class TestSqlMCPServerRepositoryGet:
    """Tests for getting MCP servers."""

    @pytest.mark.asyncio
    async def test_get_by_id_existing(self, v2_mcp_repo: SqlMCPServerRepository):
        """Test getting an MCP server by ID."""
        server_id = await v2_mcp_repo.create(
            tenant_id="tenant-test-1",
            name="Get By ID Test",
            description="Test",
            server_type="stdio",
            transport_config={},
        )

        server = await v2_mcp_repo.get_by_id(server_id)
        assert server is not None
        assert server["id"] == server_id
        assert server["name"] == "Get By ID Test"

    @pytest.mark.asyncio
    async def test_get_by_id_not_found(self, v2_mcp_repo: SqlMCPServerRepository):
        """Test getting a non-existent server returns None."""
        server = await v2_mcp_repo.get_by_id("non-existent")
        assert server is None

    @pytest.mark.asyncio
    async def test_get_by_name_existing(self, v2_mcp_repo: SqlMCPServerRepository):
        """Test getting an MCP server by name within a tenant."""
        await v2_mcp_repo.create(
            tenant_id="tenant-test-1",
            name="Unique Server Name",
            description="Test",
            server_type="stdio",
            transport_config={},
        )

        server = await v2_mcp_repo.get_by_name("tenant-test-1", "Unique Server Name")
        assert server is not None
        assert server["name"] == "Unique Server Name"

    @pytest.mark.asyncio
    async def test_get_by_name_not_found(self, v2_mcp_repo: SqlMCPServerRepository):
        """Test getting by non-existent name returns None."""
        server = await v2_mcp_repo.get_by_name("tenant-test-1", "non-existent-name")
        assert server is None


class TestSqlMCPServerRepositoryList:
    """Tests for listing MCP servers."""

    @pytest.mark.asyncio
    async def test_list_by_tenant(self, v2_mcp_repo: SqlMCPServerRepository):
        """Test listing all MCP servers for a tenant."""
        # Create multiple servers
        for i in range(3):
            await v2_mcp_repo.create(
                tenant_id="tenant-test-1",
                name=f"Server {i}",
                description=f"Description {i}",
                server_type="stdio",
                transport_config={},
            )

        # List by tenant
        servers = await v2_mcp_repo.list_by_tenant("tenant-test-1")
        assert len(servers) == 3

    @pytest.mark.asyncio
    async def test_list_by_tenant_enabled_only(self, v2_mcp_repo: SqlMCPServerRepository):
        """Test listing only enabled servers."""
        # Create enabled and disabled servers
        await v2_mcp_repo.create(
            tenant_id="tenant-test-1",
            name="Enabled Server",
            description="An enabled server",
            server_type="stdio",
            transport_config={},
            enabled=True,
        )
        await v2_mcp_repo.create(
            tenant_id="tenant-test-1",
            name="Disabled Server",
            description="A disabled server",
            server_type="stdio",
            transport_config={},
            enabled=False,
        )

        # List only enabled
        servers = await v2_mcp_repo.list_by_tenant("tenant-test-1", enabled_only=True)
        assert len(servers) == 1
        assert servers[0]["name"] == "Enabled Server"


class TestSqlMCPServerRepositoryUpdate:
    """Tests for updating MCP servers."""

    @pytest.mark.asyncio
    async def test_update_server(self, v2_mcp_repo: SqlMCPServerRepository):
        """Test updating an MCP server."""
        server_id = await v2_mcp_repo.create(
            tenant_id="tenant-test-1",
            name="Original Name",
            description="Original description",
            server_type="stdio",
            transport_config={},
        )

        # Update
        result = await v2_mcp_repo.update(
            server_id=server_id,
            name="Updated Name",
            description="Updated description",
        )

        assert result is True

        # Verify updated
        server = await v2_mcp_repo.get_by_id(server_id)
        assert server["name"] == "Updated Name"
        assert server["description"] == "Updated description"

    @pytest.mark.asyncio
    async def test_update_nonexistent_server(self, v2_mcp_repo: SqlMCPServerRepository):
        """Test updating a non-existent server returns False."""
        result = await v2_mcp_repo.update("non-existent", name="New Name")
        assert result is False

    @pytest.mark.asyncio
    async def test_update_discovered_tools(self, v2_mcp_repo: SqlMCPServerRepository):
        """Test updating discovered tools."""
        server_id = await v2_mcp_repo.create(
            tenant_id="tenant-test-1",
            name="Tools Test",
            description="Test server for tools",
            server_type="stdio",
            transport_config={},
        )

        # Update tools
        tools = [
            {"name": "tool1", "description": "First tool"},
            {"name": "tool2", "description": "Second tool"},
        ]
        timestamp = datetime.now(timezone.utc)
        result = await v2_mcp_repo.update_discovered_tools(server_id, tools, timestamp)

        assert result is True

        # Verify updated
        server = await v2_mcp_repo.get_by_id(server_id)
        assert len(server["discovered_tools"]) == 2
        assert server["discovered_tools"][0]["name"] == "tool1"


class TestSqlMCPServerRepositoryDelete:
    """Tests for deleting MCP servers."""

    @pytest.mark.asyncio
    async def test_delete_server(self, v2_mcp_repo: SqlMCPServerRepository):
        """Test deleting an MCP server."""
        server_id = await v2_mcp_repo.create(
            tenant_id="tenant-test-1",
            name="Delete Me",
            description="Server to delete",
            server_type="stdio",
            transport_config={},
        )

        # Delete
        result = await v2_mcp_repo.delete(server_id)
        assert result is True

        # Verify deleted
        server = await v2_mcp_repo.get_by_id(server_id)
        assert server is None

    @pytest.mark.asyncio
    async def test_delete_nonexistent_server(self, v2_mcp_repo: SqlMCPServerRepository):
        """Test deleting a non-existent server returns False."""
        result = await v2_mcp_repo.delete("non-existent")
        assert result is False


class TestSqlMCPServerRepositoryGetEnabledServers:
    """Tests for getting enabled servers."""

    @pytest.mark.asyncio
    async def test_get_enabled_servers(self, v2_mcp_repo: SqlMCPServerRepository):
        """Test getting all enabled MCP servers for a tenant."""
        # Create mixed servers
        await v2_mcp_repo.create(
            tenant_id="tenant-test-1",
            name="Enabled 1",
            description="First enabled",
            server_type="stdio",
            transport_config={},
            enabled=True,
        )
        await v2_mcp_repo.create(
            tenant_id="tenant-test-1",
            name="Disabled 1",
            description="A disabled server",
            server_type="stdio",
            transport_config={},
            enabled=False,
        )
        await v2_mcp_repo.create(
            tenant_id="tenant-test-1",
            name="Enabled 2",
            description="Second enabled",
            server_type="stdio",
            transport_config={},
            enabled=True,
        )

        # Get enabled
        servers = await v2_mcp_repo.get_enabled_servers("tenant-test-1")
        assert len(servers) == 2
