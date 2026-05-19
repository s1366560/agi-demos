"""
Unit tests for Provider Service.

Tests the ProviderService business logic.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from pydantic import ValidationError

from src.application.services.provider_service import ProviderService
from src.domain.llm_providers.models import (
    OperationType,
    ProviderConfigCreate,
    ProviderConfigUpdate,
    ProviderType,
)


class TestProviderService:
    """Test suite for ProviderService."""

    @pytest.fixture
    def mock_repository(self):
        """Create a mock repository."""
        repository = AsyncMock()
        repository.list_active.return_value = []
        return repository

    @pytest.fixture
    def service(self, mock_repository):
        """Create a ProviderService with mock repository."""
        with patch("src.application.services.provider_service.SQLAlchemyProviderRepository"):
            service = ProviderService(repository=mock_repository)
            return service

    @pytest.mark.asyncio
    async def test_create_provider_success(self, service):
        """Test successful provider creation."""
        config = ProviderConfigCreate(
            name="test-provider",
            provider_type=ProviderType.OPENAI,
            api_key="sk-test",
            llm_model="gpt-4o",
        )

        # Mock that provider name doesn't exist
        service.repository.get_by_name.return_value = None

        # Mock provider creation
        mock_provider = MagicMock()
        mock_provider.id = uuid4()
        service.repository.create.return_value = mock_provider

        result = await service.create_provider(config)

        assert result == mock_provider
        service.repository.create.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_provider_duplicate_name(self, service):
        """Test that duplicate provider names return existing provider."""
        config = ProviderConfigCreate(
            name="existing-provider",
            provider_type=ProviderType.OPENAI,
            api_key="sk-test",
            llm_model="gpt-4o",
        )

        # Mock that provider already exists
        existing = MagicMock()
        existing.name = "existing-provider"
        service.repository.get_by_name.return_value = existing

        result = await service.create_provider(config)
        assert result is existing
        # Should not attempt to create
        service.repository.create.assert_not_called()

    @pytest.mark.asyncio
    async def test_create_provider_clears_default_flag(self, service):
        """Test that creating a default provider clears other defaults."""
        config = ProviderConfigCreate(
            name="new-default",
            provider_type=ProviderType.OPENAI,
            api_key="sk-test",
            llm_model="gpt-4o",
            is_default=True,
        )

        # Mock existing providers with one default
        existing_default = MagicMock()
        existing_default.id = uuid4()
        existing_default.is_default = True

        service.repository.get_by_name.return_value = None
        service.repository.list_all.return_value = [existing_default]
        service.repository.update = AsyncMock()
        service.repository.create.return_value = MagicMock()

        await service.create_provider(config)

        # Should have called update to clear the existing default
        service.repository.update.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_provider_clears_only_same_operation_default(self, service):
        """Default providers are scoped independently per operation type."""
        config = ProviderConfigCreate(
            name="new-embedding-default",
            provider_type=ProviderType.OPENAI,
            operation_type=OperationType.EMBEDDING,
            api_key="sk-test",
            embedding_model="text-embedding-3-small",
            is_default=True,
        )

        llm_default = MagicMock()
        llm_default.id = uuid4()
        llm_default.is_default = True
        llm_default.operation_type = OperationType.LLM

        embedding_default = MagicMock()
        embedding_default.id = uuid4()
        embedding_default.is_default = True
        embedding_default.operation_type = OperationType.EMBEDDING

        service.repository.get_by_name.return_value = None
        service.repository.list_all.return_value = [llm_default, embedding_default]
        service.repository.update = AsyncMock()
        service.repository.create.return_value = MagicMock()

        await service.create_provider(config)

        service.repository.update.assert_called_once()
        assert service.repository.update.await_args.args[0] == embedding_default.id

    @pytest.mark.asyncio
    async def test_update_provider_success(self, service):
        """Test successful provider update."""
        provider_id = uuid4()
        config = ProviderConfigUpdate(
            name="updated-name",
        )

        existing = MagicMock()
        existing.is_default = False
        service.repository.get_by_id.return_value = existing

        updated = MagicMock()
        service.repository.update.return_value = updated

        result = await service.update_provider(provider_id, config)

        assert result == updated
        service.repository.update.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_provider_invalidates_model_pool_cache(self, service):
        """Provider updates should refresh pooled model routing immediately."""
        provider_id = uuid4()
        config = ProviderConfigUpdate(pool_enabled=False)

        existing = MagicMock()
        existing.is_default = False
        existing.operation_type = OperationType.LLM
        existing.provider_type = ProviderType.OPENAI
        service.repository.get_by_id.return_value = existing

        updated = MagicMock()
        updated.provider_type = ProviderType.OPENAI
        service.repository.update.return_value = updated

        service.resolution_service = MagicMock()

        with patch("src.infrastructure.llm.model_pool.get_model_pool_service") as mock_get_pool:
            mock_pool = MagicMock()
            mock_get_pool.return_value = mock_pool

            result = await service.update_provider(provider_id, config)

        assert result == updated
        service.resolution_service.invalidate_cache.assert_called_once()
        mock_pool.invalidate.assert_called_once_with()

    @pytest.mark.asyncio
    async def test_update_provider_not_found(self, service):
        """Test updating non-existent provider."""
        provider_id = uuid4()
        config = ProviderConfigUpdate(name="updated")

        service.repository.get_by_id.return_value = None

        result = await service.update_provider(provider_id, config)

        assert result is None

    @pytest.mark.asyncio
    async def test_delete_provider_success(self, service):
        """Test successful provider deletion."""
        provider_id = uuid4()
        service.repository.delete.return_value = True

        result = await service.delete_provider(provider_id)

        assert result is True

    @pytest.mark.asyncio
    async def test_delete_provider_not_found(self, service):
        """Test deleting non-existent provider."""
        provider_id = uuid4()
        service.repository.delete.return_value = False

        result = await service.delete_provider(provider_id)

        assert result is False

    @pytest.mark.asyncio
    async def test_assign_provider_to_tenant(self, service):
        """Test assigning provider to tenant."""
        tenant_id = "tenant-123"
        provider_id = uuid4()

        service.repository.get_by_id.return_value = MagicMock()
        service.repository.assign_provider_to_tenant.return_value = MagicMock()

        result = await service.assign_provider_to_tenant(tenant_id, provider_id, priority=0)

        assert result is not None
        service.repository.assign_provider_to_tenant.assert_called_once_with(
            tenant_id, provider_id, 0, OperationType.LLM
        )

    @pytest.mark.asyncio
    async def test_unassign_provider_from_tenant(self, service):
        """Test unassigning provider from tenant."""
        tenant_id = "tenant-123"
        provider_id = uuid4()

        service.repository.unassign_provider_from_tenant.return_value = True

        result = await service.unassign_provider_from_tenant(tenant_id, provider_id)

        assert result is True

    @pytest.mark.asyncio
    async def test_mask_api_key(self, service):
        """Test API key masking."""
        # Mock encryption service to return a test key
        with patch("src.application.services.provider_service.get_encryption_service") as mock_get:
            mock_encryption = MagicMock()
            mock_encryption.decrypt.return_value = "sk-test1234567890abcdef"
            mock_get.return_value = mock_encryption

            service = ProviderService()
            masked = service._mask_api_key("encrypted_key")

            # Should show format like "sk-test...cdef"
            assert masked.startswith("sk-")
            assert "..." in masked
            assert masked.endswith("cdef")

    @pytest.mark.asyncio
    async def test_cache_invalidation_on_create(self, service):
        """Test that cache is invalidated on provider creation."""
        config = ProviderConfigCreate(
            name="test-provider",
            provider_type=ProviderType.OPENAI,
            api_key="sk-test",
            llm_model="gpt-4o",
        )

        service.repository.get_by_name.return_value = None
        service.repository.create.return_value = MagicMock()

        # Mock resolution service
        service.resolution_service = MagicMock()

        await service.create_provider(config)

        # Should invalidate cache
        service.resolution_service.invalidate_cache.assert_called_once()

    @pytest.mark.asyncio
    async def test_cache_invalidation_on_delete(self, service):
        """Test that cache is invalidated on provider deletion."""
        provider_id = uuid4()
        service.repository.delete.return_value = True

        service.resolution_service = MagicMock()

        await service.delete_provider(provider_id)

        # Should invalidate cache
        service.resolution_service.invalidate_cache.assert_called_once()

    @pytest.mark.asyncio
    async def test_check_provider_endpoint_supports_volcengine_variants(self, service):
        """Volcengine variant provider types should use the standard Ark models endpoint."""
        provider = MagicMock()
        provider.provider_type = ProviderType.VOLCENGINE_CODING
        provider.base_url = None

        with patch.object(
            service,
            "_http_health_check",
            new=AsyncMock(return_value=("healthy", None)),
        ) as mock_health_check:
            status, error_message = await service._check_provider_endpoint(provider, "test-api-key")

        assert status == "healthy"
        assert error_message is None
        mock_health_check.assert_awaited_once()
        assert mock_health_check.await_args.kwargs["url"] == (
            "https://ark.cn-beijing.volces.com/api/v3/models"
        )
        assert mock_health_check.await_args.kwargs["headers"] == {
            "Authorization": "Bearer test-api-key"
        }

    @pytest.mark.asyncio
    async def test_test_provider_connection_checks_form_config_without_persisting(self, service):
        """Connection tests should use submitted config and avoid writing health rows."""
        config = ProviderConfigCreate(
            name="draft-openai",
            provider_type=ProviderType.OPENAI,
            api_key="sk-test",
            llm_model="gpt-4o",
        )

        with patch.object(
            service,
            "_check_provider_endpoint",
            new=AsyncMock(return_value=("healthy", None)),
        ) as mock_check:
            health = await service.test_provider_connection(config)

        assert health.status.value == "healthy"
        assert health.error_message is None
        mock_check.assert_awaited_once()
        checked_provider = mock_check.await_args.args[0]
        assert checked_provider.name == "draft-openai"
        assert checked_provider.llm_model == "gpt-4o"
        assert mock_check.await_args.args[1] == "sk-test"
        service.repository.create_health_check.assert_not_called()

    @pytest.mark.asyncio
    async def test_bedrock_health_check_requires_secret_key_config(self, service):
        """Bedrock health checks should fail fast without the AWS secret key."""
        provider = MagicMock()
        provider.config = {"region": "us-east-1"}

        status, error_message = await service._check_bedrock_provider("access-key", provider)

        assert status == "unhealthy"
        assert error_message == "Bedrock health check requires aws_secret_access_key in config"

    @pytest.mark.asyncio
    async def test_vertex_health_check_uses_configured_oauth_token(self, service):
        """Vertex health checks should call the Model Garden endpoint with OAuth auth."""
        provider = MagicMock()
        provider.config = {
            "project_id": "project-1",
            "location": "us-central1",
            "access_token": "token-1",
        }

        with patch.object(
            service,
            "_http_health_check",
            new=AsyncMock(return_value=("healthy", None)),
        ) as mock_health_check:
            status, error_message = await service._check_vertex_provider(
                MagicMock(),
                None,
                "unused-api-key",
                provider,
            )

        assert status == "healthy"
        assert error_message is None
        mock_health_check.assert_awaited_once()
        assert mock_health_check.await_args.kwargs["url"] == (
            "https://us-central1-aiplatform.googleapis.com/v1/projects/project-1/"
            "locations/us-central1/publishers/google/models"
        )
        assert mock_health_check.await_args.kwargs["headers"] == {"Authorization": "Bearer token-1"}

    @pytest.mark.asyncio
    async def test_vertex_health_check_requires_project_id(self, service):
        """Vertex health checks should return actionable config errors."""
        provider = MagicMock()
        provider.config = {"access_token": "token-1"}

        status, error_message = await service._check_vertex_provider(
            MagicMock(),
            None,
            "unused-api-key",
            provider,
        )

        assert status == "unhealthy"
        assert error_message == "Vertex AI health check requires project_id in config"

    @pytest.mark.asyncio
    async def test_delete_provider_keeps_health_registration_for_same_type(self, service):
        """Deleting one provider should keep health check registration if same-type provider remains."""
        provider_id = uuid4()
        remaining_provider = MagicMock()
        remaining_provider.id = uuid4()
        remaining_provider.provider_type = ProviderType.OPENAI
        remaining_provider.is_active = True
        remaining_provider.is_enabled = True
        remaining_provider.is_default = False
        remaining_provider.created_at = datetime.now(UTC)

        deleted_provider = MagicMock()
        deleted_provider.id = provider_id
        deleted_provider.provider_type = ProviderType.OPENAI

        service.repository.get_by_id.return_value = deleted_provider
        service.repository.delete.return_value = True
        service.repository.list_active.return_value = [remaining_provider]

        with patch(
            "src.application.services.provider_service.get_health_checker"
        ) as mock_get_checker:
            checker = MagicMock()
            mock_get_checker.return_value = checker
            await service.delete_provider(provider_id)

        checker.unregister_provider.assert_not_called()
        checker.register_provider.assert_called_once_with(ProviderType.OPENAI, remaining_provider)

    def test_provider_config_create_allows_empty_api_key_for_ollama(self):
        """Local Ollama provider should allow missing API key."""
        config = ProviderConfigCreate(
            name="local-ollama",
            provider_type=ProviderType.OLLAMA,
            api_key="",
            llm_model="llama3.1:8b",
        )
        assert config.api_key == ""

    def test_provider_config_create_requires_api_key_for_openai(self):
        """Remote providers should still require API key."""
        with pytest.raises(ValidationError):
            ProviderConfigCreate(
                name="remote-openai",
                provider_type=ProviderType.OPENAI,
                api_key="",
                llm_model="gpt-4o",
            )
