"""Integration tests for Sandbox API redirect/401 fix.

TDD: Tests written before implementation.

Problem:
- Frontend calls GET /api/v1/sandbox (no trailing slash)
- Backend route is @router.get("/") which creates /api/v1/sandbox/
- FastAPI returns 307 redirect to /api/v1/sandbox/
- Browser/client drops Authorization header on redirect (HTTP security)
- Result: 401 Unauthorized

Solution:
- Add @router.get("") route alias to handle requests without trailing slash
- This avoids the 307 redirect and preserves the Authorization header
"""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@pytest.mark.integration
class TestSandboxAPIRedirect:
    """Integration tests for sandbox API redirect/401 issue fix."""

    async def test_list_sandboxes_without_trailing_slash_returns_200(
        self,
        authenticated_async_client,
        monkeypatch,
    ):
        """Test GET /api/v1/sandbox (no trailing slash) returns 200, not 307/401.

        This test verifies that the API endpoint handles requests without
        trailing slash correctly and doesn't trigger a 307 redirect that
        would cause the Authorization header to be lost.
        """
        from src.infrastructure.adapters.secondary.sandbox.mcp_sandbox_adapter import (
            MCPSandboxAdapter,
        )

        # Mock list_sandboxes to return empty list
        async def mock_list_sandboxes(self, status=None):
            return []  # Empty list, no sandboxes

        monkeypatch.setattr(MCPSandboxAdapter, "list_sandboxes", mock_list_sandboxes)

        # Call without trailing slash - should return 200 directly
        response = await authenticated_async_client.get("/api/v1/sandbox")

        # Should return 200, not 307 (redirect) or 401 (unauthorized)
        assert response.status_code == 200, (
            f"Expected 200 OK, got {response.status_code}. "
            f"If 307, the redirect is dropping the auth header. "
            f"If 401, the auth header was lost."
        )

        # Verify response structure
        data = response.json()
        assert "sandboxes" in data
        assert "total" in data
        assert data["sandboxes"] == []
        assert data["total"] == 0

    async def test_list_sandboxes_with_trailing_slash_also_returns_200(
        self,
        authenticated_async_client,
        monkeypatch,
    ):
        """Test GET /api/v1/sandbox/ (with trailing slash) also returns 200.

        This ensures backward compatibility - both URLs should work.
        """
        from src.infrastructure.adapters.secondary.sandbox.mcp_sandbox_adapter import (
            MCPSandboxAdapter,
        )

        # Mock list_sandboxes to return empty list
        async def mock_list_sandboxes(self, status=None):
            return []

        monkeypatch.setattr(MCPSandboxAdapter, "list_sandboxes", mock_list_sandboxes)

        # Call with trailing slash
        response = await authenticated_async_client.get("/api/v1/sandbox/")

        # Should also return 200
        assert response.status_code == 200
        data = response.json()
        assert "sandboxes" in data
        assert data["total"] == 0

    async def test_list_sandboxes_unauthenticated_returns_401(
        self,
        monkeypatch,
        test_engine,
        mock_neo4j_client,
        mock_graph_service,
        mock_workflow_engine,
    ):
        """Test that unauthenticated requests still return 401."""
        from httpx import ASGITransport, AsyncClient

        from src.configuration.di_container import DIContainer
        from src.infrastructure.adapters.primary.web.dependencies import (
            get_graph_service,
            get_neo4j_client,
        )
        from src.infrastructure.adapters.primary.web.main import create_app
        from src.infrastructure.adapters.secondary.sandbox.mcp_sandbox_adapter import (
            MCPSandboxAdapter,
        )

        # Create fresh app without get_current_user override
        app = create_app()

        # Add necessary app state
        app.state.workflow_engine = mock_workflow_engine
        app.state.graph_service = mock_graph_service
        app.state.container = DIContainer(
            redis_client=None,
            graph_service=mock_graph_service,
            workflow_engine=mock_workflow_engine,
        )

        # Override only DB dependencies (keep auth intact)
        async_session = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)

        async def override_get_db():
            async with async_session() as session:
                yield session

        async def override_get_neo4j_client():
            return mock_neo4j_client

        async def override_get_graph_service():
            return mock_graph_service

        from src.infrastructure.adapters.secondary.persistence.database import get_db

        app.dependency_overrides[get_db] = override_get_db
        app.dependency_overrides[get_neo4j_client] = override_get_neo4j_client
        app.dependency_overrides[get_graph_service] = override_get_graph_service
        # Note: NOT overriding get_current_user - so auth is enforced

        # Mock list_sandboxes
        async def mock_list_sandboxes(self, status=None):
            return []

        monkeypatch.setattr(MCPSandboxAdapter, "list_sandboxes", mock_list_sandboxes)

        # Create unauthenticated client (no Authorization header)
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            # No Authorization header
        ) as client:
            response = await client.get("/api/v1/sandbox")

        # Should return 401 for unauthenticated requests
        assert response.status_code == 401

    async def test_list_sandboxes_with_data_returns_correctly(
        self,
        authenticated_async_client,
        monkeypatch,
    ):
        """Test GET /api/v1/sandbox returns sandbox data correctly."""
        from datetime import datetime
        from unittest.mock import Mock

        from src.domain.ports.services.sandbox_port import SandboxStatus
        from src.infrastructure.adapters.secondary.sandbox.mcp_sandbox_adapter import (
            MCPSandboxAdapter,
        )

        # Create mock sandbox instance
        mock_instance = Mock()
        mock_instance.id = "sandbox-123"
        mock_instance.status = SandboxStatus.RUNNING
        mock_instance.project_path = "/tmp/memstack_project-1"
        mock_instance.endpoint = "ws://localhost:8765"
        mock_instance.websocket_url = "ws://localhost:8765"
        mock_instance.created_at = datetime.now()

        # Mock list_sandboxes to return one sandbox
        async def mock_list_sandboxes(self, status=None):
            return [mock_instance]

        monkeypatch.setattr(MCPSandboxAdapter, "list_sandboxes", mock_list_sandboxes)

        # Call without trailing slash
        response = await authenticated_async_client.get("/api/v1/sandbox")

        assert response.status_code == 200
        data = response.json()
        assert len(data["sandboxes"]) == 1
        assert data["sandboxes"][0]["id"] == "sandbox-123"
        assert data["total"] == 1
