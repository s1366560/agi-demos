"""
Tests for V2 SqlMCPServerRepository using BaseRepository.
"""

from datetime import datetime, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.adapters.secondary.persistence.models import (
    Project as DBProject,
    Tenant as DBTenant,
)
from src.infrastructure.adapters.secondary.persistence.sql_mcp_server_repository import (
    SqlMCPServerRepository,
)


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


@pytest.fixture
async def test_project_db(
    db_session: AsyncSession, test_tenant_db: DBTenant
) -> DBProject:
    """Create a test project in the database."""
    project = DBProject(
        id="project-test-1",
        tenant_id=test_tenant_db.id,
        name="Test Project",
        description="A test project",
        owner_id="user-owner-1",
    )
    db_session.add(project)
    await db_session.flush()
    return project


@pytest.fixture
async def v2_mcp_repo(
    db_session: AsyncSession, test_project_db: DBProject
) -> SqlMCPServerRepository:
    """Create a V2 MCP server repository for testing."""
    return SqlMCPServerRepository(db_session)


TENANT_ID = "tenant-test-1"
PROJECT_ID = "project-test-1"


class TestSqlMCPServerRepositoryCreate:
    """Tests for creating MCP servers."""

    @pytest.mark.asyncio
    async def test_create_server(self, v2_mcp_repo: SqlMCPServerRepository):
        """Test creating a new MCP server."""
        server_id = await v2_mcp_repo.create(
            tenant_id=TENANT_ID,
            project_id=PROJECT_ID,
            name="Test Server",
            description="A test MCP server",
            server_type="stdio",
            transport_config={"command": "node", "args": ["server.js"]},
            enabled=True,
        )

        assert server_id is not None
        assert len(server_id) > 0

        server = await v2_mcp_repo.get_by_id(server_id)
        assert server is not None
        assert server["name"] == "Test Server"
        assert server["server_type"] == "stdio"
        assert server["project_id"] == PROJECT_ID


class TestSqlMCPServerRepositoryGet:
    """Tests for getting MCP servers."""

    @pytest.mark.asyncio
    async def test_get_by_id_existing(self, v2_mcp_repo: SqlMCPServerRepository):
        """Test getting an MCP server by ID."""
        server_id = await v2_mcp_repo.create(
            tenant_id=TENANT_ID,
            project_id=PROJECT_ID,
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
        """Test getting an MCP server by name within a project."""
        await v2_mcp_repo.create(
            tenant_id=TENANT_ID,
            project_id=PROJECT_ID,
            name="Unique Server Name",
            description="Test",
            server_type="stdio",
            transport_config={},
        )

        server = await v2_mcp_repo.get_by_name(PROJECT_ID, "Unique Server Name")
        assert server is not None
        assert server["name"] == "Unique Server Name"

    @pytest.mark.asyncio
    async def test_get_by_name_not_found(self, v2_mcp_repo: SqlMCPServerRepository):
        """Test getting by non-existent name returns None."""
        server = await v2_mcp_repo.get_by_name(PROJECT_ID, "non-existent-name")
        assert server is None


class TestSqlMCPServerRepositoryList:
    """Tests for listing MCP servers."""

    @pytest.mark.asyncio
    async def test_list_by_tenant(self, v2_mcp_repo: SqlMCPServerRepository):
        """Test listing all MCP servers for a tenant."""
        for i in range(3):
            await v2_mcp_repo.create(
                tenant_id=TENANT_ID,
                project_id=PROJECT_ID,
                name=f"Server {i}",
                description=f"Description {i}",
                server_type="stdio",
                transport_config={},
            )

        servers = await v2_mcp_repo.list_by_tenant(TENANT_ID)
        assert len(servers) == 3

    @pytest.mark.asyncio
    async def test_list_by_tenant_enabled_only(self, v2_mcp_repo: SqlMCPServerRepository):
        """Test listing only enabled servers."""
        await v2_mcp_repo.create(
            tenant_id=TENANT_ID,
            project_id=PROJECT_ID,
            name="Enabled Server",
            description="An enabled server",
            server_type="stdio",
            transport_config={},
            enabled=True,
        )
        await v2_mcp_repo.create(
            tenant_id=TENANT_ID,
            project_id=PROJECT_ID,
            name="Disabled Server",
            description="A disabled server",
            server_type="stdio",
            transport_config={},
            enabled=False,
        )

        servers = await v2_mcp_repo.list_by_tenant(TENANT_ID, enabled_only=True)
        assert len(servers) == 1
        assert servers[0]["name"] == "Enabled Server"

    @pytest.mark.asyncio
    async def test_list_by_project(self, v2_mcp_repo: SqlMCPServerRepository):
        """Test listing all MCP servers for a project."""
        for i in range(2):
            await v2_mcp_repo.create(
                tenant_id=TENANT_ID,
                project_id=PROJECT_ID,
                name=f"Project Server {i}",
                description=f"Description {i}",
                server_type="stdio",
                transport_config={},
            )

        servers = await v2_mcp_repo.list_by_project(PROJECT_ID)
        assert len(servers) == 2


class TestSqlMCPServerRepositoryUpdate:
    """Tests for updating MCP servers."""

    @pytest.mark.asyncio
    async def test_update_server(self, v2_mcp_repo: SqlMCPServerRepository):
        """Test updating an MCP server."""
        server_id = await v2_mcp_repo.create(
            tenant_id=TENANT_ID,
            project_id=PROJECT_ID,
            name="Original Name",
            description="Original description",
            server_type="stdio",
            transport_config={},
        )

        result = await v2_mcp_repo.update(
            server_id=server_id,
            name="Updated Name",
            description="Updated description",
        )

        assert result is True

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
            tenant_id=TENANT_ID,
            project_id=PROJECT_ID,
            name="Tools Test",
            description="Test server for tools",
            server_type="stdio",
            transport_config={},
        )

        tools = [
            {"name": "tool1", "description": "First tool"},
            {"name": "tool2", "description": "Second tool"},
        ]
        timestamp = datetime.now(timezone.utc)
        result = await v2_mcp_repo.update_discovered_tools(server_id, tools, timestamp)

        assert result is True

        server = await v2_mcp_repo.get_by_id(server_id)
        assert len(server["discovered_tools"]) == 2
        assert server["discovered_tools"][0]["name"] == "tool1"


class TestSqlMCPServerRepositoryDelete:
    """Tests for deleting MCP servers."""

    @pytest.mark.asyncio
    async def test_delete_server(self, v2_mcp_repo: SqlMCPServerRepository):
        """Test deleting an MCP server."""
        server_id = await v2_mcp_repo.create(
            tenant_id=TENANT_ID,
            project_id=PROJECT_ID,
            name="Delete Me",
            description="Server to delete",
            server_type="stdio",
            transport_config={},
        )

        result = await v2_mcp_repo.delete(server_id)
        assert result is True

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
        await v2_mcp_repo.create(
            tenant_id=TENANT_ID,
            project_id=PROJECT_ID,
            name="Enabled 1",
            description="First enabled",
            server_type="stdio",
            transport_config={},
            enabled=True,
        )
        await v2_mcp_repo.create(
            tenant_id=TENANT_ID,
            project_id=PROJECT_ID,
            name="Disabled 1",
            description="A disabled server",
            server_type="stdio",
            transport_config={},
            enabled=False,
        )
        await v2_mcp_repo.create(
            tenant_id=TENANT_ID,
            project_id=PROJECT_ID,
            name="Enabled 2",
            description="Second enabled",
            server_type="stdio",
            transport_config={},
            enabled=True,
        )

        servers = await v2_mcp_repo.get_enabled_servers(TENANT_ID)
        assert len(servers) == 2

    @pytest.mark.asyncio
    async def test_get_enabled_servers_by_project(self, v2_mcp_repo: SqlMCPServerRepository):
        """Test getting enabled servers filtered by project."""
        await v2_mcp_repo.create(
            tenant_id=TENANT_ID,
            project_id=PROJECT_ID,
            name="Project Enabled",
            description="Enabled in project",
            server_type="stdio",
            transport_config={},
            enabled=True,
        )

        servers = await v2_mcp_repo.get_enabled_servers(TENANT_ID, project_id=PROJECT_ID)
        assert len(servers) == 1
        assert servers[0]["name"] == "Project Enabled"
