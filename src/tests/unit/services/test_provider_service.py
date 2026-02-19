"""
Unit tests for Provider Service.

Tests the ProviderService business logic.
"""

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
        return AsyncMock()

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
