"""Pytest configuration and shared fixtures for testing."""

from datetime import datetime
from typing import TYPE_CHECKING, AsyncGenerator
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# DI Container
from src.configuration.di_container import DIContainer
from src.domain.model.auth.api_key import APIKey
from src.domain.model.auth.user import User as DomainUser

# Domain models
from src.domain.model.task.task_log import TaskLog
from src.infrastructure.adapters.secondary.persistence.models import (
    Base,
    Memory,
    MemoryShare,
    Notification,
    Project,
    SupportTicket,
    Tenant,
    User,
)

if TYPE_CHECKING:
    from src.infrastructure.adapters.secondary.persistence.models import Memory, Project, Tenant
from src.infrastructure.adapters.secondary.persistence.sql_api_key_repository import (
    SqlAlchemyAPIKeyRepository,
)

# Repository implementations
from src.infrastructure.adapters.secondary.persistence.sql_task_repository import (
    SqlAlchemyTaskRepository,
)
from src.infrastructure.adapters.secondary.persistence.sql_user_repository import (
    SqlAlchemyUserRepository,
)

# Constants
TEST_USER_ID = "550e8400-e29b-41d4-a716-446655440000"
TEST_TENANT_ID = "550e8400-e29b-41d4-a716-446655440001"
TEST_PROJECT_ID = "550e8400-e29b-41d4-a716-446655440002"
TEST_MEMORY_ID = "550e8400-e29b-41d4-a716-446655440003"

# --- Database Fixtures ---


@pytest.fixture
async def test_engine():
    """Create a test database engine."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
async def test_db(test_engine) -> AsyncGenerator[AsyncSession, None]:
    """Create a test database session."""
    async_session = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as session:
        yield session
        await session.rollback()


@pytest.fixture
async def db_session(test_db: AsyncSession) -> AsyncSession:
    """Alias for test_db for compatibility with existing tests."""
    return test_db


@pytest.fixture
async def db(test_db: AsyncSession) -> AsyncSession:
    """Alias for test_db for compatibility with existing tests."""
    return test_db


@pytest.fixture
async def test_tenant_db(test_db: AsyncSession, test_user: User) -> "Tenant":
    """Create a test tenant in the database with required slug field."""
    from src.infrastructure.adapters.secondary.persistence.models import Tenant, UserTenant

    tenant = Tenant(
        id=TEST_TENANT_ID,
        name="Test Tenant",
        slug="test-tenant",  # CRITICAL: Required by database schema
        description="A test tenant",
        owner_id=TEST_USER_ID,
        plan="free",
        max_projects=10,
        max_users=5,
        max_storage=1073741824,
    )
    test_db.add(tenant)

    # Add test_user as a member of the tenant (required for authorization)
    user_tenant = UserTenant(
        id=f"ut-{TEST_USER_ID}-{tenant.id}",
        user_id=TEST_USER_ID,
        tenant_id=tenant.id,
        role="owner",
        permissions={"read": True, "write": True, "admin": True},
    )
    test_db.add(user_tenant)

    await test_db.commit()
    await test_db.refresh(tenant)
    return tenant


@pytest.fixture
async def test_project_db(
    test_db: AsyncSession, test_tenant_db: "Tenant", test_user: User
) -> "Project":
    """Create a test project in the database."""
    from uuid import uuid4

    from src.infrastructure.adapters.secondary.persistence.models import Project, UserProject

    project = Project(
        id=TEST_PROJECT_ID,
        tenant_id=test_tenant_db.id,
        name="Test Project",
        description="A test project",
        owner_id=TEST_USER_ID,
        memory_rules={},
        graph_config={},
    )
    test_db.add(project)
    await test_db.commit()

    # Create UserProject relationship to add user as a member
    user_project = UserProject(
        id=str(uuid4()),
        user_id=TEST_USER_ID,
        project_id=project.id,
        role="owner",  # Make user the OWNER to fix permission issues
    )
    test_db.add(user_project)
    await test_db.commit()
    await test_db.refresh(project)
    return project


@pytest.fixture
async def test_memory_db(
    test_db: AsyncSession, test_project_db: "Project", test_user: User
) -> "Memory":
    """Create a test memory in the database."""
    from src.infrastructure.adapters.secondary.persistence.models import Memory

    memory = Memory(
        id=TEST_MEMORY_ID,
        project_id=test_project_db.id,
        title="Test Memory",
        content="Test content",
        author_id=test_user.id,
        version=1,
    )
    test_db.add(memory)
    await test_db.commit()
    await test_db.refresh(memory)
    return memory


@pytest.fixture
async def another_memory_db(
    test_db: AsyncSession, test_project_db: "Project", test_user: User
) -> "Memory":
    """Create another test memory in the database."""
    from src.infrastructure.adapters.secondary.persistence.models import Memory

    memory = Memory(
        id="memory-456",
        project_id=test_project_db.id,
        title="Another Test Memory",
        content="Another test content",
        author_id=test_user.id,
        version=1,
    )
    test_db.add(memory)
    await test_db.commit()
    await test_db.refresh(memory)
    return memory


# --- User Fixtures ---


@pytest.fixture
async def test_user(test_db: AsyncSession) -> User:
    """Create a test user (DB model) and save to database."""
    user = User(
        id=TEST_USER_ID,
        email="test@example.com",
        hashed_password="hashed_password",
        full_name="Test User",
        is_active=True,
    )
    test_db.add(user)
    await test_db.commit()
    await test_db.refresh(user)
    return user


@pytest.fixture
async def another_user(test_db: AsyncSession) -> User:
    """Create another test user for testing multi-user scenarios."""
    user = User(
        id="22222222-2222-2222-2222-222222222222",
        email="another@example.com",
        hashed_password="hashed_password",
        full_name="Another User",
        is_active=True,
    )
    test_db.add(user)
    await test_db.commit()
    await test_db.refresh(user)
    return user


@pytest.fixture
def test_domain_user() -> DomainUser:
    """Create a test user (Domain model)."""
    return DomainUser(
        id=TEST_USER_ID,
        email="test@example.com",
        password_hash="hashed_password",
        name="Test User",
        is_active=True,
    )


@pytest.fixture
def test_tenant() -> dict:
    """Create a test tenant."""
    return {
        "id": TEST_TENANT_ID,
        "name": "Test Tenant",
        "description": "A test tenant",
        "owner_id": TEST_USER_ID,
        "plan": "free",
    }


@pytest.fixture
def test_project() -> dict:
    """Create a test project."""
    return {
        "id": TEST_PROJECT_ID,
        "tenant_id": TEST_TENANT_ID,
        "name": "Test Project",
        "description": "A test project",
        "owner_id": TEST_USER_ID,
    }


# --- Repository Fixtures ---


@pytest.fixture
def task_repository(test_db):
    """Create a task repository for testing."""
    return SqlAlchemyTaskRepository(test_db)


@pytest.fixture
def user_repository(test_db):
    """Create a user repository for testing."""
    return SqlAlchemyUserRepository(test_db)


@pytest.fixture
def api_key_repository(test_db):
    """Create an API key repository for testing."""
    return SqlAlchemyAPIKeyRepository(test_db)


@pytest.fixture
def test_memory_repository(test_db):
    """Create a memory repository for testing (if exists)."""
    try:
        from src.infrastructure.adapters.secondary.persistence.sql_memory_repository import (
            SQLMemoryRepository,
        )

        return SQLMemoryRepository(test_db)
    except ImportError:
        pytest.skip("SQLMemoryRepository not available")


@pytest.fixture
def test_project_repository(test_db):
    """Create a project repository for testing (if exists)."""
    try:
        from src.infrastructure.adapters.secondary.persistence.sql_project_repository import (
            SQLProjectRepository,
        )

        return SQLProjectRepository(test_db)
    except ImportError:
        pytest.skip("SQLProjectRepository not available")


@pytest.fixture
def test_tenant_repository(test_db):
    """Create a tenant repository for testing (if exists)."""
    try:
        from src.infrastructure.adapters.secondary.persistence.sql_tenant_repository import (
            SQLTenantRepository,
        )

        return SQLTenantRepository(test_db)
    except ImportError:
        pytest.skip("SQLTenantRepository not available")


# --- DI Container Fixture ---


@pytest.fixture
def di_container(test_db, mock_graph_service):
    """Create a DI container for testing."""
    return DIContainer(test_db, graph_service=mock_graph_service)


# --- Domain Model Fixtures ---


@pytest.fixture
def test_task_log() -> TaskLog:
    """Create a test task log (Domain model)."""
    return TaskLog(
        id="task_123",
        group_id="group_123",
        task_type="test_task",
        status="PENDING",
        payload={"test": "data"},
    )


@pytest.fixture
def test_api_key() -> APIKey:
    """Create a test API key (Domain model)."""
    return APIKey(
        id="key_123",
        user_id="user_123",
        key_hash="hashed_key",
        name="Test Key",
        permissions=["read", "write"],
    )


@pytest.fixture
def test_token() -> str:
    """Create a valid JWT token for testing authentication."""
    # For testing, we can use a mock token or generate a real one
    # This fixture provides a Bearer token string
    return "Bearer ms_sk_test_token_123456789"


# --- Neo4j and Graph Service Mock Fixtures ---


@pytest.fixture
def mock_neo4j_client():
    """Create a mock Neo4j client for direct graph queries."""
    from unittest.mock import AsyncMock, Mock

    client = Mock()

    # Mock execute_query to return proper mock results
    def mock_execute_query(query, **kwargs):
        """Mock execute_query to handle various queries."""
        mock_result = Mock()
        mock_result.records = []

        # Handle count queries - return total=0
        if "count" in query.lower():
            mock_record = {"total": 0}
            mock_result.records = [mock_record]
        # Handle list queries - return empty list
        elif "return properties" in query.lower():
            pass  # Empty records list
        # Handle delete queries
        elif "delete" in query.lower() or "detach delete" in query.lower():
            mock_record = {"deleted": 0}
            mock_result.records = [mock_record]

        return mock_result

    client.execute_query = AsyncMock(side_effect=mock_execute_query)

    # Mock close
    client.close = AsyncMock()

    return client


@pytest.fixture
def mock_graphiti_client(mock_neo4j_client):
    """Legacy fixture - alias for mock_neo4j_client for backward compatibility."""
    return mock_neo4j_client


@pytest.fixture
def mock_graph_service(mock_neo4j_client):
    """Create a mock GraphServicePort (NativeGraphAdapter).

    This mock simulates the NativeGraphAdapter interface used by routers
    that call graph_service.add_episode(), graph_service.search() etc.
    """
    from unittest.mock import AsyncMock, Mock

    service = Mock()
    # Expose the underlying client for tests that need direct Neo4j access
    service.client = mock_neo4j_client

    # Mock GraphServicePort methods
    service.add_episode = AsyncMock()
    service.search = AsyncMock(return_value=[])
    service.hybrid_search = AsyncMock(return_value=[])
    service.get_graph_data = AsyncMock(return_value={"nodes": [], "edges": []})
    service.delete_episode = AsyncMock(return_value=True)
    service.remove_episode = AsyncMock(return_value=True)
    service.remove_episode_by_memory_id = AsyncMock(return_value=True)

    return service


# --- Service Mock Fixtures ---


@pytest.fixture
def mock_search_service():
    """Create a mock search service for testing."""
    service = AsyncMock()
    service.search = AsyncMock(return_value=[])
    service.search_by_vector = AsyncMock(return_value=[])
    return service


@pytest.fixture
def mock_embedding_service():
    """Create a mock embedding service for testing."""
    service = AsyncMock()
    service.embed = AsyncMock(return_value=[0.1, 0.2, 0.3])
    service.embed_batch = AsyncMock(return_value=[[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]])
    return service


@pytest.fixture
def mock_memory_repo():
    """Create a mock memory repository for testing."""
    repo = AsyncMock()
    repo.create = AsyncMock()
    repo.find_by_id = AsyncMock()
    repo.find_by_project = AsyncMock()
    repo.update = AsyncMock()
    repo.delete = AsyncMock()
    repo.list = AsyncMock(return_value=[])
    return repo


@pytest.fixture
def mock_db_session():
    """Create a mock database session for testing."""
    from unittest.mock import Mock

    session = Mock()
    session.add = Mock()
    session.commit = Mock()
    session.rollback = Mock()
    session.refresh = Mock()
    session.execute = Mock()
    session.query = Mock()
    return session


@pytest.fixture
def mock_graphiti_service(mock_graph_service):
    """Legacy fixture - alias for mock_graph_service for backward compatibility."""
    return mock_graph_service


@pytest.fixture
def mock_llm_service():
    """Create a mock LLM service for testing."""
    service = AsyncMock()
    service.generate_response = AsyncMock(return_value="Test response")
    service.generate_structured = AsyncMock(return_value={"result": "test"})
    return service


@pytest.fixture
def mock_redis_client():
    """Create a mock Redis client for testing."""
    client = Mock()
    client.get = Mock(return_value=None)
    client.set = Mock(return_value=True)
    client.delete = Mock(return_value=1)
    client.exists = Mock(return_value=0)
    client.expire = Mock(return_value=True)
    client.ping = Mock(return_value=True)
    return client


# --- FastAPI Test Client Fixtures ---


@pytest.fixture
def test_app(mock_neo4j_client, mock_graph_service, test_engine, mock_workflow_engine):
    """Create a test FastAPI application."""

    from src.configuration.di_container import DIContainer
    from src.infrastructure.adapters.primary.web.dependencies import (
        get_current_user,
        get_graph_service,
        get_neo4j_client,
    )
    from src.infrastructure.adapters.primary.web.main import create_app
    from src.infrastructure.adapters.secondary.persistence.database import get_db
    from src.infrastructure.adapters.secondary.persistence.models import User

    app = create_app()

    # Add workflow_engine to app state
    app.state.workflow_engine = mock_workflow_engine

    # Add graph_service to app state
    app.state.graph_service = mock_graph_service

    # Add container to app state for agent endpoints
    app.state.container = DIContainer(
        redis_client=None,  # Mock for tests
        graph_service=mock_graph_service,
        workflow_engine=mock_workflow_engine,
    )

    # Override database dependency to use test SQLite database
    # This ensures integration tests use the same database as test fixtures
    async_session = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)

    async def override_get_db():
        async with async_session() as session:
            yield session

    async def override_get_neo4j_client():
        return mock_neo4j_client

    async def override_get_graph_service():
        return mock_graph_service

    async def override_get_current_user():
        # Create a test user directly instead of calling fixture
        user = User(
            id=TEST_USER_ID,
            email="test@example.com",
            hashed_password="hashed_password",
            full_name="Test User",
            is_active=True,
        )
        # Add tenant_id for agent endpoints that expect it
        user.tenant_id = "default_tenant"
        # Add empty roles and tenants relationships for tests
        user.roles = []
        user.tenants = []
        return user

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_neo4j_client] = override_get_neo4j_client
    app.dependency_overrides[get_graph_service] = override_get_graph_service
    app.dependency_overrides[get_current_user] = override_get_current_user

    return app


@pytest.fixture
def client(test_app):
    """Create a test client for the FastAPI application."""
    return TestClient(test_app)


@pytest.fixture
def authenticated_client(test_app, test_token):
    """Create an authenticated test client with pre-configured Bearer token."""
    from fastapi.testclient import TestClient

    return TestClient(test_app, headers={"Authorization": test_token})


@pytest.fixture
async def async_client(test_app):
    """Create an async test client for the FastAPI application."""
    from httpx import ASGITransport, AsyncClient

    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as client:
        yield client


@pytest.fixture
async def authenticated_async_client(test_app, test_token):
    """Create an authenticated async test client with pre-configured Bearer token."""
    from httpx import ASGITransport, AsyncClient

    async with AsyncClient(
        transport=ASGITransport(app=test_app),
        base_url="http://test",
        headers={"Authorization": test_token},
    ) as client:
        yield client


# --- Mock Workflow Engine ---


@pytest.fixture
def mock_workflow_engine():
    """Create a mock workflow engine."""
    engine = Mock()
    engine.start_workflow = AsyncMock(
        return_value=Mock(workflow_id="workflow_123", run_id="run_123")
    )
    engine.get_workflow_status = AsyncMock(return_value=Mock(status="COMPLETED"))
    return engine


# For backward compatibility with tests that still reference mock_queue_service
@pytest.fixture
def mock_queue_service(mock_workflow_engine):
    """Alias for mock_workflow_engine for backward compatibility."""
    return mock_workflow_engine


# --- Test Data Helpers ---


@pytest.fixture
def sample_episode_data() -> dict:
    """Sample episode data for testing."""
    return {
        "name": "Test Episode",
        "content": "This is a test episode content.",
        "source_description": "text",
        "episode_type": "text",
        "project_id": "proj_123",
        "tenant_id": "tenant_123",
        "user_id": "user_123",
    }


@pytest.fixture
def sample_memory_data() -> dict:
    """Sample memory data for testing."""
    return {
        "project_id": "proj_123",
        "title": "Test Memory",
        "content": "This is test memory content.",
        "author_id": "user_123",
        "tenant_id": "tenant_123",
        "content_type": "text",
        "tags": ["tag1", "tag2"],
        "is_public": False,
    }


@pytest.fixture
def sample_entity_data() -> dict:
    """Sample entity data for testing."""
    return {
        "uuid": "entity_123",
        "name": "TestEntity",
        "entity_type": "Organization",
        "summary": "A test organization",
        "tenant_id": "tenant_123",
        "project_id": "proj_123",
        "created_at": datetime.utcnow().isoformat(),
    }


# --- Async Event Loop Fixture ---


@pytest.fixture(scope="session")
def event_loop():
    """Create an instance of the event loop for the test session."""
    import asyncio

    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


# --- Support Fixtures ---
@pytest.fixture
async def test_support_ticket(test_db: AsyncSession, test_user: User) -> SupportTicket:
    ticket = SupportTicket(
        id="ticket_test_1",
        user_id=test_user.id,
        subject="Support Subject",
        message="Support message",
        priority="medium",
        status="open",
    )
    test_db.add(ticket)
    await test_db.commit()
    await test_db.refresh(ticket)
    return ticket


@pytest.fixture
async def test_memory_with_project(test_db: AsyncSession, test_user: User) -> Memory:
    project = Project(
        id="proj_test_mem",
        tenant_id="tenant_123",
        name="Project for Memory Share",
        description="Test project",
        owner_id=test_user.id,
        is_public=False,
    )
    test_db.add(project)
    memory = Memory(
        id="mem_share_test",
        project_id=project.id,
        title="Shareable Memory",
        content="Some content",
        author_id=test_user.id,
        content_type="text",
        is_public=False,
    )
    test_db.add(memory)
    await test_db.commit()
    await test_db.refresh(memory)
    return memory


@pytest.fixture
async def test_memory_share(
    test_db: AsyncSession, test_memory_with_project: Memory, test_user: User
) -> MemoryShare:
    share = MemoryShare(
        id="share_test_1",
        memory_id=test_memory_with_project.id,
        share_token="token_test_123",
        shared_by=test_user.id,
        permissions={"view": True},
        access_count=0,
    )
    test_db.add(share)
    await test_db.commit()
    await test_db.refresh(share)
    return share


@pytest.fixture
async def test_notification(test_db: AsyncSession, test_user: User) -> Notification:
    notif = Notification(
        id="notif_test_1",
        user_id=test_user.id,
        type="info",
        title="Test Notification",
        message="Hello",
        is_read=False,
    )
    test_db.add(notif)
    await test_db.commit()
    await test_db.refresh(notif)
    return notif


@pytest.fixture
async def test_tenant_in_db(test_db: AsyncSession, test_user: User) -> dict:
    tenant = Tenant(
        id="tenant_in_db_1",
        name="Tenant In DB",
        slug="tenant-in-db",
        description="For billing tests",
        owner_id=test_user.id,
    )
    test_db.add(tenant)
    await test_db.commit()
    await test_db.refresh(tenant)
    return {"id": tenant.id, "name": tenant.name}


# --- Sandbox Fixtures ---


@pytest.fixture
def test_sandbox_id() -> str:
    """Provide a test sandbox ID for sandbox-related tests."""
    return "test-sandbox-12345"
