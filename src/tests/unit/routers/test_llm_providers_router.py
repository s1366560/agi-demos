"""Unit tests for LLM providers router."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, Mock, patch
from uuid import uuid4

import pytest
from fastapi import status
from fastapi.testclient import TestClient

from src.domain.llm_providers.models import (
    ProviderConfigResponse,
    ProviderHealth,
    ProviderStatus,
    ProviderType,
    ProviderValidationResponse,
)


def create_provider_response(
    provider_id: str | None = None,
    name: str = "test-openai",
    provider_type: ProviderType = ProviderType.OPENAI,
    is_active: bool = True,
    is_default: bool = False,
) -> ProviderConfigResponse:
    """Create a ProviderConfigResponse for testing."""
    if provider_id is None:
        provider_id = str(uuid4())
    return ProviderConfigResponse(
        id=provider_id,
        name=name,
        provider_type=provider_type,
        llm_model="gpt-4o",
        llm_small_model="gpt-4o-mini",
        embedding_model="text-embedding-3-small",
        reranker_model=None,
        base_url=None,
        config={},
        is_active=is_active,
        is_default=is_default,
        api_key_masked="sk-...xyz",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        health_status=ProviderStatus.HEALTHY,
        health_last_check=datetime.now(UTC),
        response_time_ms=150,
        error_message=None,
    )


@pytest.fixture
def mock_provider_service():
    """Create a mock provider service."""
    service = AsyncMock()
    service.create_provider = AsyncMock()
    service.list_providers = AsyncMock(return_value=[])
    service.get_provider_responses = AsyncMock(return_value=[])
    service.get_provider_response = AsyncMock()
    service.update_provider = AsyncMock()
    service.delete_provider = AsyncMock(return_value=True)
    service.check_provider_health = AsyncMock()
    service.test_provider_connection = AsyncMock()
    service.assign_provider_to_tenant = AsyncMock()
    service.get_tenant_providers = AsyncMock(return_value=[])
    service.unassign_provider_from_tenant = AsyncMock(return_value=True)
    service.resolve_provider_for_tenant = AsyncMock()
    service.get_usage_statistics = AsyncMock(return_value=[])
    return service


@pytest.fixture
def sample_provider_data():
    """Sample provider data for testing."""
    return {
        "name": "test-openai",
        "provider_type": "openai",
        "api_key": "sk-test-key-12345",
        "llm_model": "gpt-4o",
        "llm_small_model": "gpt-4o-mini",
        "embedding_model": "text-embedding-3-small",
        "is_active": True,
        "is_default": False,
    }


@pytest.fixture
def admin_user():
    """Create an admin user for testing."""
    user = Mock()
    user.id = str(uuid4())
    user.email = "admin@example.com"
    user.full_name = "Admin User"
    user.is_active = True
    user.tenants = []

    # Mock admin role
    mock_role = Mock()
    mock_role.role = Mock()
    mock_role.role.name = "admin"
    user.roles = [mock_role]

    return user


@pytest.fixture
def regular_user():
    """Create a regular (non-admin) user for testing."""
    user = Mock()
    user.id = str(uuid4())
    user.email = "user@example.com"
    user.full_name = "Regular User"
    user.is_active = True
    tenant_membership = Mock()
    tenant_membership.tenant_id = str(uuid4())
    user.tenants = [tenant_membership]

    # Mock regular user role
    mock_role = Mock()
    mock_role.role = Mock()
    mock_role.role.name = "user"
    user.roles = [mock_role]

    return user


@pytest.fixture
def llm_providers_app(mock_provider_service, admin_user):
    """Create a test FastAPI app with only LLM providers router."""
    from fastapi import FastAPI

    from src.infrastructure.adapters.primary.web.dependencies import get_current_user
    from src.infrastructure.adapters.primary.web.routers.llm_providers import (
        get_current_user_with_roles,
        get_provider_service_with_session,
        router,
    )

    app = FastAPI()
    app.include_router(router)

    # Override dependencies — must override both get_current_user (used by
    # list_provider_types, list_models) and get_current_user_with_roles
    # (used by CRUD endpoints that need role checks)
    app.dependency_overrides[get_current_user] = lambda: admin_user
    app.dependency_overrides[get_current_user_with_roles] = lambda: admin_user
    app.dependency_overrides[get_provider_service_with_session] = lambda: mock_provider_service

    return app


@pytest.fixture
def llm_client(llm_providers_app):
    """Create a test client for the LLM providers app."""
    return TestClient(llm_providers_app)


@pytest.mark.unit
class TestLLMProvidersRouterCreate:
    """Test cases for provider creation endpoint."""

    @pytest.mark.asyncio
    async def test_create_provider_success(
        self, llm_client, mock_provider_service, sample_provider_data
    ):
        """Test successful provider creation by admin."""
        provider_id = str(uuid4())

        # Mock provider creation
        mock_provider = Mock()
        mock_provider.id = provider_id
        mock_provider_service.create_provider.return_value = mock_provider

        # Mock provider response with actual Pydantic model
        mock_provider_service.get_provider_response.return_value = create_provider_response(
            provider_id=provider_id,
            name=sample_provider_data["name"],
        )

        response = llm_client.post(
            "/api/v1/llm-providers/",
            json=sample_provider_data,
        )

        assert response.status_code == status.HTTP_201_CREATED
        mock_provider_service.create_provider.assert_called_once()
        data = response.json()
        assert data["name"] == sample_provider_data["name"]

    @pytest.mark.asyncio
    async def test_create_provider_forbidden_for_non_admin(
        self, llm_providers_app, sample_provider_data, regular_user
    ):
        """Test that non-admin users cannot create providers."""
        from src.infrastructure.adapters.primary.web.routers.llm_providers import (
            get_current_user_with_roles,
        )

        # Override to use regular user
        llm_providers_app.dependency_overrides[get_current_user_with_roles] = lambda: regular_user
        client = TestClient(llm_providers_app)

        response = client.post(
            "/api/v1/llm-providers/",
            json=sample_provider_data,
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert "Admin access required" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_create_provider_validation_error(self, llm_client, mock_provider_service):
        """Test validation error when creating provider with bad data."""
        # When the service raises ValueError, we get 400
        mock_provider_service.create_provider.side_effect = ValueError(
            "Duplicate provider name: secret-provider"
        )

        response = llm_client.post(
            "/api/v1/llm-providers/",
            json={
                "name": "duplicate-provider",
                "provider_type": "openai",
                "api_key": "sk-test",
                "llm_model": "gpt-4o",
            },
        )

        # Should get 400 due to ValueError in service
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["detail"] == "Invalid provider request"
        assert "secret-provider" not in response.text


@pytest.mark.unit
class TestLLMProvidersRouterList:
    """Test cases for provider listing endpoint."""

    @pytest.mark.asyncio
    async def test_list_providers_success(self, llm_client, mock_provider_service):
        """Test listing providers."""
        mock_provider_service.list_providers.return_value = []

        response = llm_client.get("/api/v1/llm-providers/")

        assert response.status_code == status.HTTP_200_OK
        mock_provider_service.get_provider_responses.assert_called_once_with([])
        assert isinstance(response.json(), list)

    @pytest.mark.asyncio
    async def test_list_providers_with_data(self, llm_client, mock_provider_service):
        """Test listing providers with data."""
        provider_id = str(uuid4())

        mock_provider = Mock()
        mock_provider.id = provider_id
        mock_provider_service.list_providers.return_value = [mock_provider]

        # Use actual Pydantic model
        mock_provider_service.get_provider_responses.return_value = [
            create_provider_response(provider_id=provider_id, name="test-provider")
        ]

        response = llm_client.get("/api/v1/llm-providers/")

        assert response.status_code == status.HTTP_200_OK
        mock_provider_service.list_providers.assert_called_once()
        mock_provider_service.get_provider_responses.assert_called_once_with([mock_provider])
        mock_provider_service.get_provider_response.assert_not_called()
        data = response.json()
        assert len(data) == 1
        assert data[0]["name"] == "test-provider"

    @pytest.mark.asyncio
    async def test_list_providers_non_admin_excludes_inactive(
        self, llm_providers_app, mock_provider_service, regular_user
    ):
        """Test that non-admin users cannot see inactive providers."""
        from src.infrastructure.adapters.primary.web.routers.llm_providers import (
            get_current_user_with_roles,
        )

        llm_providers_app.dependency_overrides[get_current_user_with_roles] = lambda: regular_user
        client = TestClient(llm_providers_app)

        mock_provider_service.list_providers.return_value = []

        response = client.get("/api/v1/llm-providers/?include_inactive=true")

        assert response.status_code == status.HTTP_200_OK
        # Verify that include_inactive was forced to False for non-admin
        mock_provider_service.list_providers.assert_called_once()
        call_kwargs = mock_provider_service.list_providers.call_args.kwargs
        assert call_kwargs.get("include_inactive") is False


@pytest.mark.unit
class TestLLMProvidersRouterGet:
    """Test cases for getting a specific provider."""

    @pytest.mark.asyncio
    async def test_get_provider_success(self, llm_client, mock_provider_service):
        """Test getting a specific provider."""
        provider_id = str(uuid4())

        # Use actual Pydantic model
        mock_provider_service.get_provider_response.return_value = create_provider_response(
            provider_id=provider_id,
            name="test-provider",
        )

        response = llm_client.get(f"/api/v1/llm-providers/{provider_id}")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["name"] == "test-provider"

    @pytest.mark.asyncio
    async def test_get_provider_not_found(self, llm_client, mock_provider_service):
        """Test getting a non-existent provider."""
        provider_id = str(uuid4())

        mock_provider_service.get_provider_response.return_value = None

        response = llm_client.get(f"/api/v1/llm-providers/{provider_id}")

        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert "Provider not found" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_get_inactive_provider_hidden_for_non_admin(
        self, llm_providers_app, mock_provider_service, regular_user
    ):
        """Test that non-admin users cannot see inactive providers."""
        from src.infrastructure.adapters.primary.web.routers.llm_providers import (
            get_current_user_with_roles,
        )

        llm_providers_app.dependency_overrides[get_current_user_with_roles] = lambda: regular_user
        client = TestClient(llm_providers_app)

        provider_id = str(uuid4())

        # Use actual Pydantic model with is_active=False
        mock_provider_service.get_provider_response.return_value = create_provider_response(
            provider_id=provider_id,
            name="test-provider",
            is_active=False,
        )

        response = client.get(f"/api/v1/llm-providers/{provider_id}")

        assert response.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.unit
class TestLLMProvidersRouterUpdate:
    """Test cases for provider update endpoint."""

    @pytest.mark.asyncio
    async def test_update_provider_success(self, llm_client, mock_provider_service):
        """Test updating a provider."""
        provider_id = str(uuid4())

        mock_updated = Mock()
        mock_updated.id = provider_id
        mock_updated.name = "updated-name"
        mock_provider_service.update_provider.return_value = mock_updated

        # Use actual Pydantic model
        mock_provider_service.get_provider_response.return_value = create_provider_response(
            provider_id=provider_id,
            name="updated-name",
        )

        response = llm_client.put(
            f"/api/v1/llm-providers/{provider_id}",
            json={"name": "updated-name"},
        )

        assert response.status_code == status.HTTP_200_OK
        mock_provider_service.update_provider.assert_called_once()
        data = response.json()
        assert data["name"] == "updated-name"

    @pytest.mark.asyncio
    async def test_update_provider_not_found(self, llm_client, mock_provider_service):
        """Test updating a non-existent provider."""
        provider_id = str(uuid4())

        mock_provider_service.update_provider.return_value = None

        response = llm_client.put(
            f"/api/v1/llm-providers/{provider_id}",
            json={"name": "updated-name"},
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND

    @pytest.mark.asyncio
    async def test_update_provider_forbidden_for_non_admin(self, llm_providers_app, regular_user):
        """Test that non-admin users cannot update providers."""
        from src.infrastructure.adapters.primary.web.routers.llm_providers import (
            get_current_user_with_roles,
        )

        llm_providers_app.dependency_overrides[get_current_user_with_roles] = lambda: regular_user
        client = TestClient(llm_providers_app)

        provider_id = str(uuid4())

        response = client.put(
            f"/api/v1/llm-providers/{provider_id}",
            json={"name": "updated-name"},
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.unit
class TestLLMProvidersRouterDelete:
    """Test cases for provider deletion endpoint."""

    @pytest.mark.asyncio
    async def test_delete_provider_success(self, llm_client, mock_provider_service):
        """Test deleting a provider."""
        provider_id = str(uuid4())

        mock_provider_service.delete_provider.return_value = True

        response = llm_client.delete(f"/api/v1/llm-providers/{provider_id}")

        assert response.status_code == status.HTTP_204_NO_CONTENT
        mock_provider_service.delete_provider.assert_called_once()

    @pytest.mark.asyncio
    async def test_delete_provider_not_found(self, llm_client, mock_provider_service):
        """Test deleting a non-existent provider."""
        provider_id = str(uuid4())

        mock_provider_service.delete_provider.return_value = False

        response = llm_client.delete(f"/api/v1/llm-providers/{provider_id}")

        assert response.status_code == status.HTTP_404_NOT_FOUND

    @pytest.mark.asyncio
    async def test_delete_provider_forbidden_for_non_admin(self, llm_providers_app, regular_user):
        """Test that non-admin users cannot delete providers."""
        from src.infrastructure.adapters.primary.web.routers.llm_providers import (
            get_current_user_with_roles,
        )

        llm_providers_app.dependency_overrides[get_current_user_with_roles] = lambda: regular_user
        client = TestClient(llm_providers_app)

        provider_id = str(uuid4())

        response = client.delete(f"/api/v1/llm-providers/{provider_id}")

        assert response.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.unit
class TestLLMProvidersRouterHealthCheck:
    """Test cases for provider health check endpoints."""

    @pytest.mark.asyncio
    async def test_test_provider_connection_success(self, llm_client, mock_provider_service):
        """Test a provider connection without saving it."""
        checked_at = datetime.now(UTC)
        mock_validation = ProviderValidationResponse(
            provider=None,
            provider_id=uuid4(),
            status=ProviderStatus.HEALTHY,
            probed=True,
            detail=None,
            catalog=None,
            response_time_ms=120,
            last_check=checked_at,
            error_message=None,
        )
        mock_provider_service.test_provider_connection.return_value = mock_validation

        response = llm_client.post(
            "/api/v1/llm-providers/test-connection",
            json={
                "name": "test-openai",
                "provider_type": "openai",
                "api_key": "sk-test-key-12345",
            },
        )

        assert response.status_code == status.HTTP_200_OK
        mock_provider_service.test_provider_connection.assert_called_once()
        data = response.json()
        assert data == {
            "provider": None,
            "provider_id": str(mock_validation.provider_id),
            "status": "healthy",
            "probed": True,
            "detail": None,
            "last_check": checked_at.isoformat().replace("+00:00", "Z"),
            "response_time_ms": 120,
            "error_message": None,
            "catalog": None,
        }
        submitted = mock_provider_service.test_provider_connection.call_args.args[0]
        assert submitted.name == "test-openai"
        assert not hasattr(submitted, "llm_model")

    @pytest.mark.asyncio
    async def test_test_provider_connection_validation_error(
        self,
        llm_client,
        mock_provider_service,
    ):
        """Test connection errors are not exposed verbatim."""
        mock_provider_service.test_provider_connection.side_effect = ValueError(
            "Provider base_url contains internal-hostname"
        )

        response = llm_client.post(
            "/api/v1/llm-providers/test-connection",
            json={
                "name": "test-openai",
                "provider_type": "openai",
                "api_key": "sk-test-key-12345",
                "llm_model": "gpt-4o",
            },
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["detail"] == "Provider connection test failed"
        assert "internal-hostname" not in response.text

    @pytest.mark.asyncio
    async def test_check_provider_health_success(self, llm_client, mock_provider_service):
        """Test triggering a health check."""
        provider_id = str(uuid4())

        # Use actual Pydantic model for health response
        mock_health = ProviderHealth(
            provider_id=provider_id,
            status=ProviderStatus.HEALTHY,
            response_time_ms=150,
            last_check=datetime.now(UTC),
            error_message=None,
        )
        mock_provider_service.check_provider_health.return_value = mock_health

        response = llm_client.post(f"/api/v1/llm-providers/{provider_id}/health-check")

        assert response.status_code == status.HTTP_200_OK
        mock_provider_service.check_provider_health.assert_called_once()
        data = response.json()
        assert data["status"] == "healthy"
        assert data["probed"] is True
        assert data["detail"] is None
        assert data["catalog"] is None

    @pytest.mark.asyncio
    async def test_check_provider_health_not_found(self, llm_client, mock_provider_service):
        """Test health check for non-existent provider."""
        provider_id = uuid4()

        mock_provider_service.check_provider_health.side_effect = ValueError(
            f"Provider not found: {provider_id}"
        )

        response = llm_client.post(f"/api/v1/llm-providers/{provider_id}/health-check")

        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert response.json()["detail"] == "Provider not found"
        assert str(provider_id) not in response.text


@pytest.mark.unit
class TestLLMProvidersRouterTenantAssignment:
    """Test cases for tenant-provider assignment endpoints."""

    @pytest.mark.asyncio
    async def test_list_tenant_assignments_for_member_tenant(
        self, llm_providers_app, mock_provider_service, regular_user
    ):
        """Test that a regular user can list assignments for a tenant they belong to."""
        from src.infrastructure.adapters.primary.web.routers.llm_providers import (
            get_current_user_with_roles,
        )

        llm_providers_app.dependency_overrides[get_current_user_with_roles] = lambda: regular_user
        client = TestClient(llm_providers_app)
        tenant_id = regular_user.tenants[0].tenant_id

        response = client.get(f"/api/v1/llm-providers/tenants/{tenant_id}/assignments")

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == []
        mock_provider_service.get_tenant_providers.assert_called_once_with(tenant_id, None)

    @pytest.mark.asyncio
    async def test_list_tenant_assignments_for_other_tenant_forbidden(
        self, llm_providers_app, mock_provider_service, regular_user
    ):
        """Test that a regular user cannot list another tenant's assignments."""
        from src.infrastructure.adapters.primary.web.routers.llm_providers import (
            get_current_user_with_roles,
        )

        llm_providers_app.dependency_overrides[get_current_user_with_roles] = lambda: regular_user
        client = TestClient(llm_providers_app)

        response = client.get("/api/v1/llm-providers/tenants/other-tenant/assignments")

        assert response.status_code == status.HTTP_403_FORBIDDEN
        mock_provider_service.get_tenant_providers.assert_not_called()

    @pytest.mark.asyncio
    async def test_assign_provider_to_tenant_success(self, llm_client, mock_provider_service):
        """Test assigning a provider to a tenant."""
        provider_id = str(uuid4())
        tenant_id = "tenant-123"

        mock_mapping = Mock()
        mock_mapping.id = str(uuid4())
        mock_mapping.operation_type = "llm"
        mock_provider_service.assign_provider_to_tenant.return_value = mock_mapping

        response = llm_client.post(
            f"/api/v1/llm-providers/tenants/{tenant_id}/providers/{provider_id}?priority=0"
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["message"] == "Provider assigned to tenant"
        assert "mapping_id" in data
        mock_provider_service.assign_provider_to_tenant.assert_called_once()

    @pytest.mark.asyncio
    async def test_assign_provider_validation_error(self, llm_client, mock_provider_service):
        """Test assignment with validation error."""
        provider_id = str(uuid4())
        tenant_id = "tenant-123"

        mock_provider_service.assign_provider_to_tenant.side_effect = ValueError(
            f"Provider not found: {provider_id}"
        )

        response = llm_client.post(
            f"/api/v1/llm-providers/tenants/{tenant_id}/providers/{provider_id}"
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["detail"] == "Provider assignment failed"
        assert provider_id not in response.text
        assert tenant_id not in response.text

    @pytest.mark.asyncio
    async def test_unassign_provider_from_tenant_success(self, llm_client, mock_provider_service):
        """Test unassigning a provider from a tenant."""
        provider_id = str(uuid4())
        tenant_id = "tenant-123"

        mock_provider_service.unassign_provider_from_tenant.return_value = True

        response = llm_client.delete(
            f"/api/v1/llm-providers/tenants/{tenant_id}/providers/{provider_id}"
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["message"] == "Provider unassigned from tenant"

    @pytest.mark.asyncio
    async def test_unassign_provider_not_found(self, llm_client, mock_provider_service):
        """Test unassigning a non-existent mapping."""
        provider_id = str(uuid4())
        tenant_id = "tenant-123"

        mock_provider_service.unassign_provider_from_tenant.return_value = False

        response = llm_client.delete(
            f"/api/v1/llm-providers/tenants/{tenant_id}/providers/{provider_id}"
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND

    @pytest.mark.asyncio
    async def test_get_tenant_provider_success(self, llm_client, mock_provider_service):
        """Test getting the provider for a tenant."""
        provider_id = str(uuid4())
        tenant_id = "tenant-123"

        mock_provider = Mock()
        mock_provider.id = provider_id
        mock_provider_service.resolve_provider_for_tenant.return_value = mock_provider

        # Use actual Pydantic model
        mock_provider_service.get_provider_response.return_value = create_provider_response(
            provider_id=provider_id,
            name="tenant-provider",
        )

        response = llm_client.get(f"/api/v1/llm-providers/tenants/{tenant_id}/provider")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["name"] == "tenant-provider"

    @pytest.mark.asyncio
    async def test_get_tenant_provider_no_active_provider(self, llm_client, mock_provider_service):
        """Test getting tenant provider when no active provider exists."""
        from src.domain.llm_providers.models import NoActiveProviderError

        tenant_id = "tenant-123"

        mock_provider_service.resolve_provider_for_tenant.side_effect = NoActiveProviderError(
            f"No active provider found for tenant {tenant_id}"
        )

        response = llm_client.get(f"/api/v1/llm-providers/tenants/{tenant_id}/provider")

        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert response.json()["detail"] == "No active provider configured"
        assert tenant_id not in response.text

    @pytest.mark.asyncio
    async def test_get_tenant_provider_for_other_tenant_forbidden(
        self, llm_providers_app, mock_provider_service, regular_user
    ):
        """Test that a regular user cannot resolve another tenant's provider."""
        from src.infrastructure.adapters.primary.web.routers.llm_providers import (
            get_current_user_with_roles,
        )

        llm_providers_app.dependency_overrides[get_current_user_with_roles] = lambda: regular_user
        client = TestClient(llm_providers_app)

        response = client.get("/api/v1/llm-providers/tenants/other-tenant/provider")

        assert response.status_code == status.HTTP_403_FORBIDDEN
        mock_provider_service.resolve_provider_for_tenant.assert_not_called()


@pytest.mark.unit
class TestLLMProvidersRouterTypes:
    """Test cases for provider type information endpoints."""

    def test_list_provider_types(self, llm_client):
        """Test listing supported provider types."""
        response = llm_client.get("/api/v1/llm-providers/types")

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == [
            {
                "provider_type": provider_type.value,
                "auth_methods": (
                    ["none"]
                    if provider_type in {ProviderType.OLLAMA, ProviderType.LMSTUDIO}
                    else ["api_key"]
                ),
            }
            for provider_type in ProviderType
        ]

    def test_detect_env_providers_reports_credential_metadata_without_secret(self, llm_client):
        """Environment detection reports configuration state without returning secrets."""
        secret = "sk-must-not-leak"
        detected = {
            "openai": {
                "operation_type": "llm",
                "api_key": secret,
                "base_url": "https://api.openai.com/v1",
                "llm_model": "gpt-4o",
                "llm_small_model": "gpt-4o-mini",
                "embedding_model": "text-embedding-3-small",
                "reranker_model": None,
            },
            "ollama": {
                "operation_type": "llm",
                "base_url": "http://localhost:11434",
                "llm_model": "qwen3",
            },
        }

        with patch(
            "src.infrastructure.llm.initializer.detect_env_providers",
            return_value=detected,
        ):
            response = llm_client.get("/api/v1/llm-providers/env-detection")

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {
            "detected_providers": {
                "openai": {
                    "provider_type": "openai",
                    "operation_type": "llm",
                    "credential_source": "environment",
                    "credential_configured": True,
                    "base_url": "https://api.openai.com/v1",
                    "llm_model": "gpt-4o",
                    "llm_small_model": "gpt-4o-mini",
                    "embedding_model": "text-embedding-3-small",
                    "reranker_model": None,
                },
                "ollama": {
                    "provider_type": "ollama",
                    "operation_type": "llm",
                    "credential_source": "environment",
                    "credential_configured": False,
                    "base_url": "http://localhost:11434",
                    "llm_model": "qwen3",
                    "llm_small_model": None,
                    "embedding_model": None,
                    "reranker_model": None,
                },
            }
        }
        assert "api_key" not in response.text
        assert secret not in response.text

    @pytest.mark.asyncio
    async def test_list_models_for_openai(self, llm_client):
        """Test listing models for OpenAI provider type."""
        response = llm_client.get("/api/v1/llm-providers/models/openai")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["provider_type"] == "openai"
        assert "models" in data
        assert data["source"] == "models.dev"
        assert data["models"]["chat"]
        assert "text-embedding-3-small" in data["models"]["embedding"]

    @pytest.mark.asyncio
    async def test_list_models_for_openrouter(self, llm_client):
        """Test listing models for OpenRouter provider type."""
        response = llm_client.get("/api/v1/llm-providers/models/openrouter")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["provider_type"] == "openrouter"
        assert data["source"] == "models.dev"
        assert data["models"]["chat"]

    @pytest.mark.asyncio
    async def test_list_models_for_dashscope(self, llm_client):
        """Test listing models for Dashscope provider type."""
        response = llm_client.get("/api/v1/llm-providers/models/dashscope")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["provider_type"] == "dashscope"
        assert "models" in data

    @pytest.mark.asyncio
    async def test_list_models_for_gemini(self, llm_client):
        """Test listing models for Gemini provider type."""
        response = llm_client.get("/api/v1/llm-providers/models/gemini")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["provider_type"] == "gemini"

    @pytest.mark.asyncio
    async def test_list_models_for_minimax(self, llm_client):
        """Test listing models for MiniMax provider type."""
        response = llm_client.get("/api/v1/llm-providers/models/minimax")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["provider_type"] == "minimax"
        assert data["source"] == "models.dev"
        assert data["models"]["chat"]

    @pytest.mark.asyncio
    async def test_list_models_for_kimi(self, llm_client):
        """Test listing models for Kimi provider type."""
        response = llm_client.get("/api/v1/llm-providers/models/kimi")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["provider_type"] == "kimi"
        assert data["source"] == "models.dev"
        assert "models" in data

    @pytest.mark.asyncio
    async def test_list_models_for_zai(self, llm_client):
        """Test listing models for ZAI provider type."""
        response = llm_client.get("/api/v1/llm-providers/models/zai")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["provider_type"] == "zai"
        assert data["source"] == "models.dev"
        assert "models" in data

    @pytest.mark.asyncio
    async def test_list_models_for_ollama(self, llm_client):
        """Test listing models for Ollama provider type."""
        response = llm_client.get("/api/v1/llm-providers/models/ollama")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["provider_type"] == "ollama"
        assert "nomic-embed-text" in data["models"]["embedding"]

    @pytest.mark.asyncio
    async def test_list_models_for_lmstudio(self, llm_client):
        """Test listing models for LM Studio provider type."""
        response = llm_client.get("/api/v1/llm-providers/models/lmstudio")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["provider_type"] == "lmstudio"
        assert "local-model" in data["models"]["chat"]

    @pytest.mark.asyncio
    async def test_list_models_unknown_provider(self, llm_client):
        """Test listing models for an unknown provider type."""
        response = llm_client.get("/api/v1/llm-providers/models/unknown_provider")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["models"] == {"chat": [], "embedding": [], "rerank": []}


@pytest.mark.unit
class TestLLMProvidersRouterUsage:
    """Test cases for provider usage statistics endpoint."""

    @pytest.mark.asyncio
    async def test_get_provider_usage_admin(self, llm_client, mock_provider_service):
        """Test getting usage statistics as admin."""
        provider_id = str(uuid4())

        mock_provider_service.get_usage_statistics.return_value = []

        response = llm_client.get(f"/api/v1/llm-providers/{provider_id}/usage")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "provider_id" in data
        assert "statistics" in data
        assert data["tenant_id"] is None  # Admin sees all

    @pytest.mark.asyncio
    async def test_get_provider_usage_non_admin_scoped_to_tenant(
        self, llm_providers_app, mock_provider_service, regular_user
    ):
        """Test that non-admin users only see their tenant's usage."""
        from src.infrastructure.adapters.primary.web.routers.llm_providers import (
            get_current_user_with_roles,
        )

        llm_providers_app.dependency_overrides[get_current_user_with_roles] = lambda: regular_user
        client = TestClient(llm_providers_app)

        provider_id = str(uuid4())

        mock_provider_service.get_usage_statistics.return_value = []

        response = client.get(f"/api/v1/llm-providers/{provider_id}/usage")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["tenant_id"] == regular_user.tenants[0].tenant_id

    @pytest.mark.asyncio
    async def test_get_provider_usage_with_filters(self, llm_client, mock_provider_service):
        """Test getting usage statistics with date filters."""
        provider_id = str(uuid4())

        mock_provider_service.get_usage_statistics.return_value = []

        response = llm_client.get(
            f"/api/v1/llm-providers/{provider_id}/usage"
            "?start_date=2024-01-01T00:00:00&end_date=2024-12-31T23:59:59"
            "&operation_type=llm"
        )

        assert response.status_code == status.HTTP_200_OK
        mock_provider_service.get_usage_statistics.assert_called_once()


@pytest.mark.unit
class TestLLMProvidersRouterSystem:
    """Test cases for provider system maintenance endpoints."""

    def test_reset_circuit_breaker_sanitizes_internal_errors(self, llm_client, monkeypatch):
        """Registry failures should not leak backend exception details."""
        import src.infrastructure.llm.resilience as resilience

        def raise_registry_error():
            raise RuntimeError("redis://secret-host/provider-registry")

        monkeypatch.setattr(resilience, "get_circuit_breaker_registry", raise_registry_error)

        response = llm_client.post("/api/v1/llm-providers/system/reset-circuit-breaker/openai")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["detail"] == "Failed to reset circuit breaker"
        assert "secret-host" not in response.text
