"""
Unit tests for Provider Service.

Tests the ProviderService business logic.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from pydantic import ValidationError

from src.application.services.provider_service import ProviderService
from src.domain.llm_providers.models import (
    EmbeddingConfig,
    OperationType,
    ProviderAuthMethod,
    ProviderConfig,
    ProviderConfigCreate,
    ProviderConfigUpdate,
    ProviderCredentialRequiredError,
    ProviderHealth,
    ProviderProbeRequest,
    ProviderStatus,
    ProviderType,
    UnsupportedProviderAuthError,
    provider_revision,
)
from src.infrastructure.llm.provider_credentials import NO_API_KEY_SENTINEL


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
    async def test_create_provider_delegates_default_replacement_to_repository(self, service):
        """Default replacement belongs to the repository create transaction."""
        config = ProviderConfigCreate(
            name="new-default",
            provider_type=ProviderType.OPENAI,
            api_key="sk-test",
            llm_model="gpt-4o",
            is_default=True,
        )
        service.repository.get_by_name.return_value = None
        created = MagicMock()
        service.repository.create.return_value = created

        result = await service.create_provider(config)

        assert result is created
        service.repository.list_all.assert_not_awaited()
        service.repository.update.assert_not_awaited()
        service.repository.create.assert_awaited_once_with(config)

    @pytest.mark.asyncio
    async def test_create_embedding_default_does_not_clear_defaults_in_service(self, service):
        """Operation-scoped default handling is not split across service calls."""
        config = ProviderConfigCreate(
            name="new-embedding-default",
            provider_type=ProviderType.OPENAI,
            operation_type=OperationType.EMBEDDING,
            api_key="sk-test",
            embedding_model="text-embedding-3-small",
            is_default=True,
        )
        service.repository.get_by_name.return_value = None
        service.repository.create.return_value = MagicMock()

        await service.create_provider(config)

        service.repository.list_all.assert_not_awaited()
        service.repository.update.assert_not_awaited()
        service.repository.create.assert_awaited_once_with(config)

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
    async def test_update_provider_delegates_default_switch_to_repository_transaction(
        self, service
    ):
        """Default replacement must share the target revision-check transaction."""
        provider_id = uuid4()
        now = datetime.now(UTC)
        existing = ProviderConfig(
            id=provider_id,
            name="next-default",
            provider_type=ProviderType.OPENAI,
            operation_type=OperationType.LLM,
            api_key_encrypted="encrypted-key",
            llm_model="gpt-4o",
            is_default=False,
            created_at=now,
            updated_at=now,
        )
        config = ProviderConfigUpdate(
            expected_revision=provider_revision(existing.updated_at),
            is_default=True,
        )
        updated = existing.model_copy(update={"is_default": True})
        service.repository.get_by_id.return_value = existing
        service.repository.update.return_value = updated

        result = await service.update_provider(provider_id, config)

        assert result is updated
        service.repository.list_all.assert_not_awaited()
        service.repository.update.assert_awaited_once_with(
            provider_id,
            config,
            replace_default_for=OperationType.LLM,
        )

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
    async def test_update_remote_endpoint_requires_resubmitted_api_key(self, service):
        """An encrypted key is never silently rebound to a different remote origin."""
        provider_id = uuid4()
        now = datetime.now(UTC)
        existing = ProviderConfig(
            id=provider_id,
            name="remote-openai",
            provider_type=ProviderType.OPENAI,
            api_key_encrypted="encrypted-old-key",
            base_url="https://api.openai.com/v1",
            llm_model="gpt-4o",
            created_at=now,
            updated_at=now,
        )
        service.repository.get_by_id.return_value = existing

        with pytest.raises(ProviderCredentialRequiredError, match="must be resubmitted"):
            await service.update_provider(
                provider_id,
                ProviderConfigUpdate(base_url="https://proxy.example/v1"),
            )

        service.repository.update.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_update_remote_endpoint_passes_resubmitted_api_key_to_repository(self, service):
        """A new remote origin and its replacement credential persist in one update."""
        provider_id = uuid4()
        now = datetime.now(UTC)
        existing = ProviderConfig(
            id=provider_id,
            name="remote-openai",
            provider_type=ProviderType.OPENAI,
            api_key_encrypted="encrypted-old-key",
            base_url="https://api.openai.com/v1",
            llm_model="gpt-4o",
            created_at=now,
            updated_at=now,
        )
        updated = existing.model_copy(
            update={"base_url": "https://proxy.example/v1", "updated_at": now}
        )
        service.repository.get_by_id.return_value = existing
        service.repository.update.return_value = updated

        result = await service.update_provider(
            provider_id,
            ProviderConfigUpdate(
                base_url="https://proxy.example/v1",
                api_key="sk-new-origin-key",
            ),
        )

        assert result is updated
        submitted = service.repository.update.await_args.args[1]
        assert submitted.base_url == "https://proxy.example/v1"
        assert submitted.api_key == "sk-new-origin-key"

    @pytest.mark.asyncio
    async def test_clear_remote_endpoint_requires_resubmitted_api_key(self, service):
        """Clearing a custom endpoint is a binding change, not an absent update."""
        provider_id = uuid4()
        now = datetime.now(UTC)
        service.repository.get_by_id.return_value = ProviderConfig(
            id=provider_id,
            name="remote-openai",
            provider_type=ProviderType.OPENAI,
            api_key_encrypted="encrypted-old-key",
            base_url="https://proxy.example/v1",
            llm_model="gpt-4o",
            created_at=now,
            updated_at=now,
        )

        with pytest.raises(ProviderCredentialRequiredError):
            await service.update_provider(
                provider_id,
                ProviderConfigUpdate(base_url=""),
            )

        service.repository.update.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_get_provider_responses_reuses_loaded_provider_configs(self, service):
        """List responses should not re-fetch provider rows one by one."""
        now = datetime.now(UTC)
        provider_id = uuid4()
        provider = ProviderConfig(
            id=provider_id,
            name="test-provider",
            provider_type=ProviderType.OPENAI,
            api_key_encrypted="encrypted-key",
            llm_model="gpt-4o",
            created_at=now,
            updated_at=now,
        )
        service.repository.get_latest_health.return_value = ProviderHealth(
            provider_id=provider_id,
            status=ProviderStatus.HEALTHY,
            last_check=now,
            response_time_ms=125,
        )

        with (
            patch.object(service, "_mask_api_key", return_value="sk-test...cdef") as mask_api_key,
            patch.object(service, "_get_resilience_status", return_value=None),
        ):
            responses = await service.get_provider_responses([provider])

        assert len(responses) == 1
        assert responses[0].id == provider_id
        assert responses[0].name == "test-provider"
        assert responses[0].api_key_masked == "sk-test...cdef"
        assert responses[0].health_status == ProviderStatus.HEALTHY
        service.repository.get_by_id.assert_not_called()
        service.repository.get_latest_health.assert_awaited_once_with(provider_id)
        mask_api_key.assert_called_once_with("encrypted-key")

    @pytest.mark.asyncio
    async def test_provider_response_omits_health_older_than_provider_update(self, service):
        """A status recorded for an old credential/config revision is not current health."""
        updated_at = datetime.now(UTC)
        provider_id = uuid4()
        provider = ProviderConfig(
            id=provider_id,
            name="updated-provider",
            provider_type=ProviderType.OPENAI,
            api_key_encrypted="encrypted-key",
            llm_model="gpt-4o",
            created_at=updated_at - timedelta(minutes=5),
            updated_at=updated_at,
        )
        service.repository.get_latest_health.return_value = ProviderHealth(
            provider_id=provider_id,
            status=ProviderStatus.HEALTHY,
            last_check=updated_at - timedelta(seconds=1),
            response_time_ms=90,
        )
        service.encryption_service = MagicMock()
        service.encryption_service.decrypt.return_value = "sk-current-secret"

        response = await service._provider_to_response(provider)

        assert response.health_status is None
        assert response.health_last_check is None
        assert response.response_time_ms is None

    @pytest.mark.asyncio
    async def test_provider_response_projects_encrypted_api_key_and_redacts_config(self, service):
        """API responses expose credential state while recursively removing config secrets."""
        now = datetime.now(UTC)
        provider_id = uuid4()
        persisted_config = {
            "region": "us-east-1",
            "api_key": "config-api-key-value",
            "apiSecret": "camel-api-secret-value",
            "apiCredential": "unanticipated-api-credential",
            "credentialValue": "unanticipated-credential-value",
            "auth": "unanticipated-auth-value",
            "secret": "unanticipated-secret-value",
            "secretKey": "camel-secret-key-value",
            "token": "generic-token-value",
            "credential": "generic-credential-value",
            "password": "config-password-value",
            "aws_secret_access_key": "aws-secret-value",
            "credentials": {
                "secret_access_key": "generic-secret-value",
                "aws_session_token": "aws-session-secret-value",
                "safe": "credential-metadata",
            },
            "nested": {
                "access_token": "access-secret-value",
                "safe": "visible",
            },
            "request": {
                "headers": {
                    "Authorization": "Bearer header-secret-value",
                    "X-Api-Key": "header-api-secret-value",
                },
                "timeout": 30,
            },
            "items": [
                {"oauth_token": "oauth-secret-value", "safe": "kept"},
                {"session_token": "session-secret-value"},
            ],
        }
        provider = ProviderConfig(
            id=provider_id,
            name="remote-openai",
            provider_type=ProviderType.OPENAI,
            api_key_encrypted="encrypted-key",
            llm_model="gpt-4o",
            embedding_config=EmbeddingConfig(
                model="text-embedding-3-small",
                provider_options={
                    "access_token": "embedding-access-secret",
                    "custom_headers": {"X-Api-Key": "embedding-header-secret"},
                    "batch_size": 32,
                },
            ),
            config=persisted_config,
            created_at=now,
            updated_at=now,
        )
        service.repository.get_latest_health.return_value = None
        service.encryption_service = MagicMock()
        service.encryption_service.decrypt.return_value = "sk-runtime-only-secret"

        response = await service._provider_to_response(provider)

        assert response.auth_method == ProviderAuthMethod.API_KEY
        assert response.environment_variable is None
        assert response.credential_source == "service_encrypted"
        assert response.credential_configured is True
        assert response.revision == provider_revision(now)
        assert response.config == {"region": "us-east-1"}
        assert response.embedding_config is not None
        assert response.embedding_config.model == "text-embedding-3-small"
        assert response.embedding_config.provider_options == {"batch_size": 32}
        serialized = response.model_dump_json()
        for secret_key in (
            "aws_secret_access_key",
            "password",
            "secret_access_key",
            "aws_session_token",
            "access_token",
            "headers",
            "Authorization",
            "oauth_token",
            "session_token",
        ):
            assert secret_key not in serialized
        for secret_value in (
            "aws-secret-value",
            "config-api-key-value",
            "camel-api-secret-value",
            "camel-secret-key-value",
            "generic-token-value",
            "generic-credential-value",
            "unanticipated-api-credential",
            "unanticipated-credential-value",
            "unanticipated-auth-value",
            "unanticipated-secret-value",
            "config-password-value",
            "generic-secret-value",
            "aws-session-secret-value",
            "access-secret-value",
            "header-secret-value",
            "header-api-secret-value",
            "oauth-secret-value",
            "session-secret-value",
            "embedding-access-secret",
            "embedding-header-secret",
        ):
            assert secret_value not in serialized
        assert provider.config == persisted_config

    @pytest.mark.asyncio
    async def test_provider_response_projects_no_auth_without_credential_inference(self, service):
        """Local no-auth providers never infer a persisted environment or API-key credential."""
        now = datetime.now(UTC)
        provider = ProviderConfig(
            id=uuid4(),
            name="local-ollama",
            provider_type=ProviderType.OLLAMA,
            api_key_encrypted="encrypted-no-key",
            llm_model="llama3.1:8b",
            created_at=now,
            updated_at=now,
        )
        service.repository.get_latest_health.return_value = None
        service.encryption_service = MagicMock()
        service.encryption_service.decrypt.return_value = NO_API_KEY_SENTINEL

        response = await service._provider_to_response(provider)

        assert response.auth_method == ProviderAuthMethod.NONE
        assert response.environment_variable is None
        assert response.credential_source == "none"
        assert response.credential_configured is True
        assert response.api_key_masked == "(local-no-key)"
        service.encryption_service.decrypt.assert_not_called()

    @pytest.mark.asyncio
    async def test_provider_response_hides_historical_unsafe_base_url(self, service):
        """Existing unsafe endpoints are not echoed back even before data cleanup runs."""
        now = datetime.now(UTC)
        provider = ProviderConfig(
            id=uuid4(),
            name="historical-openai",
            provider_type=ProviderType.OPENAI,
            api_key_encrypted="encrypted-key",
            base_url="https://example.test/tenant-path-token",
            llm_model="gpt-4o",
            created_at=now,
            updated_at=now,
        )
        service.repository.get_latest_health.return_value = None
        service.encryption_service = MagicMock()
        service.encryption_service.decrypt.return_value = "sk-current-secret"

        response = await service._provider_to_response(provider)

        assert response.base_url is None
        assert "tenant-path-token" not in response.model_dump_json()

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

    def test_mask_api_key_invalid_format_log_omits_exception_content(self, service, caplog):
        """Invalid encrypted key logs must not include raw exception content."""
        exception_detail = "invalid encrypted api key leaked secret provider-secret-1357"
        service.encryption_service = MagicMock()
        service.encryption_service.decrypt.side_effect = ValueError(exception_detail)

        with caplog.at_level("WARNING", logger="src.application.services.provider_service"):
            masked = service._mask_api_key("encrypted-provider-secret-1357")

        assert masked == "sk-[ERROR]"
        assert exception_detail not in caplog.text
        assert "provider-secret-1357" not in caplog.text
        assert "error_type=ValueError" in caplog.text

    def test_mask_api_key_unexpected_error_log_omits_exception_content(self, service, caplog):
        """Unexpected encrypted key errors must not include raw exception content."""
        exception_detail = "decrypt backend leaked api key provider-secret-2468"
        service.encryption_service = MagicMock()
        service.encryption_service.decrypt.side_effect = RuntimeError(exception_detail)

        with caplog.at_level("ERROR", logger="src.application.services.provider_service"):
            masked = service._mask_api_key("encrypted-provider-secret-2468")

        assert masked == "sk-[ERROR]"
        assert exception_detail not in caplog.text
        assert "provider-secret-2468" not in caplog.text
        assert "error_type=RuntimeError" in caplog.text

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
    async def test_saved_local_provider_health_check_does_not_require_an_api_key(self, service):
        """Persisted Ollama/LM Studio sentinel credentials must not block endpoint probing."""
        now = datetime.now(UTC)
        provider_id = uuid4()
        provider = ProviderConfig(
            id=provider_id,
            name="local-ollama",
            provider_type=ProviderType.OLLAMA,
            api_key_encrypted="encrypted-no-key",
            base_url="http://127.0.0.1:11434",
            llm_model="llama3.1:8b",
            created_at=now,
            updated_at=now,
        )
        service.repository.get_by_id.return_value = provider
        service.encryption_service = MagicMock()
        service.encryption_service.decrypt.return_value = NO_API_KEY_SENTINEL

        with patch.object(
            service,
            "_check_provider_endpoint",
            new=AsyncMock(return_value=("healthy", None)),
        ) as mock_check:
            health = await service.check_provider_health(provider_id)

        assert health.status == ProviderStatus.HEALTHY
        assert health.error_message is None
        mock_check.assert_awaited_once_with(provider, "")
        service.repository.create_health_check.assert_awaited_once_with(health)

    @pytest.mark.asyncio
    async def test_saved_unsupported_probe_returns_configuration_valid_without_network(
        self,
        service,
    ):
        """Saved providers without a safe probe remain explicitly configuration-valid."""
        now = datetime.now(UTC)
        provider = ProviderConfig(
            id=uuid4(),
            name="historical-azure",
            provider_type=ProviderType.AZURE_OPENAI,
            api_key_encrypted="encrypted-historical-key",
            base_url="https://resource.openai.azure.com/v1",
            llm_model="deployment-name",
            created_at=now,
            updated_at=now,
        )
        service.repository.get_by_id.return_value = provider
        service.encryption_service = MagicMock()

        with patch.object(service, "_check_provider_endpoint", new=AsyncMock()) as mock_check:
            health = await service.check_provider_health(provider.id)

        assert health.provider_id == provider.id
        assert health.status == ProviderStatus.CONFIGURATION_VALID
        assert health.response_time_ms is None
        assert health.error_message is None
        mock_check.assert_not_awaited()
        service.encryption_service.decrypt.assert_not_called()
        service.repository.create_health_check.assert_awaited_once_with(health)

    @pytest.mark.asyncio
    async def test_test_provider_connection_checks_form_config_without_persisting(self, service):
        """Connection tests should use submitted config and avoid writing health rows."""
        config = ProviderProbeRequest(
            name="draft-openai",
            provider_type=ProviderType.OPENAI,
            api_key="sk-test",
        )

        with patch.object(
            service,
            "_check_provider_endpoint",
            new=AsyncMock(return_value=("healthy", None)),
        ) as mock_check:
            validation = await service.test_provider_connection(config)

        assert validation.status.value == "healthy"
        assert validation.probed is True
        assert validation.detail is None
        assert validation.catalog is None
        assert validation.error_message is None
        mock_check.assert_awaited_once()
        checked_provider = mock_check.await_args.args[0]
        assert checked_provider.name == "draft-openai"
        assert checked_provider.llm_model is None
        assert mock_check.await_args.args[1] == "sk-test"
        service.repository.create_health_check.assert_not_called()

    @pytest.mark.asyncio
    async def test_test_provider_connection_resolves_environment_reference_at_probe_time(
        self,
        service,
    ):
        """Environment auth resolves an allow-listed variable without returning its value."""
        secret = "sk-runtime-only-secret"
        config = ProviderProbeRequest(
            name="environment-openai",
            provider_type=ProviderType.OPENAI,
            auth_method=ProviderAuthMethod.ENVIRONMENT,
            environment_variable="OPENAI_API_KEY",
        )

        with (
            patch.dict("os.environ", {"OPENAI_API_KEY": secret}),
            patch.object(
                service,
                "_check_provider_endpoint",
                new=AsyncMock(return_value=("healthy", None)),
            ) as mock_check,
        ):
            validation = await service.test_provider_connection(config)

        assert validation.status == ProviderStatus.HEALTHY
        assert validation.probed is True
        assert validation.environment_variable == "OPENAI_API_KEY"
        assert mock_check.await_args.args[1] == secret
        assert secret not in validation.model_dump_json()

    @pytest.mark.asyncio
    async def test_environment_probe_rejects_custom_origin_before_reading_credential(
        self,
        service,
    ):
        """An allow-listed environment secret cannot be sent to a custom HTTPS host."""
        config = ProviderProbeRequest(
            name="environment-openai-proxy",
            provider_type=ProviderType.OPENAI,
            auth_method=ProviderAuthMethod.ENVIRONMENT,
            environment_variable="OPENAI_API_KEY",
            base_url="https://attacker.example/v1",
        )

        with (
            patch.dict("os.environ", {"OPENAI_API_KEY": "sk-runtime-only-secret"}),
            patch.object(service, "_check_provider_endpoint", new=AsyncMock()) as mock_check,
            pytest.raises(ValueError, match="official provider endpoint"),
        ):
            await service.test_provider_connection(config)

        mock_check.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_test_provider_connection_reports_missing_environment_credential_without_probe(
        self,
        service,
    ):
        """A missing environment variable is an explicit validation result, not a network probe."""
        config = ProviderProbeRequest(
            name="missing-environment-openai",
            provider_type=ProviderType.OPENAI,
            auth_method=ProviderAuthMethod.ENVIRONMENT,
            environment_variable="OPENAI_API_KEY",
        )

        with (
            patch.dict("os.environ", {}, clear=True),
            patch.object(service, "_check_provider_endpoint", new=AsyncMock()) as mock_check,
        ):
            validation = await service.test_provider_connection(config)

        assert validation.status == ProviderStatus.UNHEALTHY
        assert validation.probed is False
        assert validation.detail == "Environment credential is not configured"
        assert validation.environment_variable == "OPENAI_API_KEY"
        mock_check.assert_not_awaited()

    def test_probe_request_rejects_arbitrary_environment_variable_names(self):
        """Provider environment auth cannot read unrelated server variables."""
        with pytest.raises(
            ValueError,
            match="Environment variable is not supported for this provider type",
        ):
            ProviderProbeRequest(
                name="unsafe-environment-reference",
                provider_type=ProviderType.OPENAI,
                auth_method=ProviderAuthMethod.ENVIRONMENT,
                environment_variable="DATABASE_URL",
            )

    def test_probe_request_rejects_oauth_until_backend_flow_exists(self):
        """OAuth is an explicit unsupported method instead of an ignored draft field."""
        with pytest.raises(ValidationError, match="OAuth authentication is not supported"):
            ProviderProbeRequest(
                name="oauth-openai",
                provider_type=ProviderType.OPENAI,
                auth_method=ProviderAuthMethod.OAUTH,
            )

    @pytest.mark.parametrize(
        "provider_type,base_url",
        [
            (ProviderType.OPENAI, "http://api.openai.example/v1"),
            (ProviderType.OPENAI, "file:///tmp/provider"),
            (ProviderType.OPENAI, "https://user:pass@example.test/v1"),
            (ProviderType.OPENAI, "https://example.test/v1?api_key=secret"),
            (ProviderType.OPENAI, "https://example.test/v1#secret"),
            (ProviderType.OLLAMA, "http://ollama.example.test:11434"),
        ],
    )
    def test_probe_request_rejects_unsafe_provider_base_urls(
        self,
        provider_type,
        base_url,
    ):
        """Probe credentials cannot be routed through unsafe endpoint transports."""
        is_local = provider_type == ProviderType.OLLAMA
        with pytest.raises(ValidationError):
            ProviderProbeRequest(
                name="unsafe-endpoint",
                provider_type=provider_type,
                api_key=None if is_local else "sk-test",
                base_url=base_url,
            )

    def test_probe_request_accepts_loopback_http_for_local_provider(self):
        """Local no-auth endpoints remain usable over loopback HTTP."""
        request = ProviderProbeRequest(
            name="local-ollama",
            provider_type=ProviderType.OLLAMA,
            base_url="http://127.0.0.1:11434",
        )

        assert request.base_url == "http://127.0.0.1:11434"

    @pytest.mark.asyncio
    async def test_update_provider_validates_base_url_against_existing_provider_type(self, service):
        """Partial updates cannot bypass the remote-provider HTTPS requirement."""
        provider_id = uuid4()
        now = datetime.now(UTC)
        service.repository.get_by_id.return_value = ProviderConfig(
            id=provider_id,
            name="remote-openai",
            provider_type=ProviderType.OPENAI,
            api_key_encrypted="encrypted-key",
            base_url="https://api.openai.com/v1",
            llm_model="gpt-4o",
            created_at=now,
            updated_at=now,
        )

        with pytest.raises(ValueError, match="HTTPS is required"):
            await service.update_provider(
                provider_id,
                ProviderConfigUpdate(base_url="http://127.0.0.1:8080/v1"),
            )

        service.repository.update.assert_not_awaited()

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
        assert config.auth_method == ProviderAuthMethod.NONE
        assert config.environment_variable is None

    def test_provider_config_create_requires_api_key_for_openai(self):
        """Remote providers should still require API key."""
        with pytest.raises(ValidationError):
            ProviderConfigCreate(
                name="remote-openai",
                provider_type=ProviderType.OPENAI,
                api_key="",
                llm_model="gpt-4o",
            )

    def test_provider_config_create_defaults_remote_provider_to_api_key(self):
        """Remote persistent providers project the executable API-key auth method."""
        config = ProviderConfigCreate(
            name="remote-openai",
            provider_type=ProviderType.OPENAI,
            api_key="sk-test",
            llm_model="gpt-4o",
        )

        assert config.auth_method == ProviderAuthMethod.API_KEY
        assert config.environment_variable is None

    @pytest.mark.parametrize("auth_method", ["environment", "oauth"])
    def test_provider_config_create_rejects_unpersistable_auth_methods(self, auth_method):
        """Persistent CRUD cannot silently accept auth methods the repository cannot execute."""
        with pytest.raises(ValidationError, match="not supported for persistent providers"):
            ProviderConfigCreate(
                name="unsupported-auth-openai",
                provider_type=ProviderType.OPENAI,
                auth_method=auth_method,
                environment_variable=("OPENAI_API_KEY" if auth_method == "environment" else None),
                llm_model="gpt-4o",
            )

    def test_provider_config_create_forbids_unknown_fields(self):
        """Typos and future fields must fail instead of being silently discarded."""
        with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
            ProviderConfigCreate.model_validate(
                {
                    "name": "strict-openai",
                    "provider_type": "openai",
                    "auth_method": "api_key",
                    "api_key": "sk-test",
                    "llm_model": "gpt-4o",
                    "credential_value": "must-not-be-ignored",
                }
            )

    @pytest.mark.parametrize("auth_method", ["environment", "oauth"])
    def test_provider_config_update_rejects_unpersistable_auth_methods(self, auth_method):
        """Updates reject unsupported credential sources before reaching persistence."""
        with pytest.raises(ValidationError, match="not supported for persistent providers"):
            ProviderConfigUpdate(
                auth_method=auth_method,
                environment_variable=("OPENAI_API_KEY" if auth_method == "environment" else None),
            )

    def test_provider_config_update_forbids_unknown_fields(self):
        """Update payloads must not ignore unknown authentication fields."""
        with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
            ProviderConfigUpdate.model_validate({"credential_value": "must-not-be-ignored"})

    @pytest.mark.asyncio
    async def test_update_local_provider_rejects_api_key_auth(self, service):
        """Service validation uses the persisted provider type for partial updates."""
        provider_id = uuid4()
        existing = MagicMock()
        existing.provider_type = ProviderType.OLLAMA
        existing.operation_type = OperationType.LLM
        existing.is_default = False
        service.repository.get_by_id.return_value = existing

        with pytest.raises(ValueError, match="not supported for local providers"):
            await service.update_provider(
                provider_id,
                ProviderConfigUpdate(auth_method=ProviderAuthMethod.API_KEY, api_key="sk-test"),
            )

        service.repository.update.assert_not_called()

    @pytest.mark.asyncio
    async def test_update_remote_provider_reuses_configured_encrypted_api_key(self, service):
        """An API-key update may keep the existing encrypted value when it is usable."""
        provider_id = uuid4()
        existing = MagicMock()
        existing.provider_type = ProviderType.OPENAI
        existing.operation_type = OperationType.LLM
        existing.is_default = False
        existing.api_key_encrypted = "encrypted-key"
        updated = MagicMock()
        updated.provider_type = ProviderType.OPENAI
        service.repository.get_by_id.return_value = existing
        service.repository.update.return_value = updated
        service.encryption_service = MagicMock()
        service.encryption_service.decrypt.return_value = "sk-existing"

        result = await service.update_provider(
            provider_id,
            ProviderConfigUpdate(auth_method=ProviderAuthMethod.API_KEY),
        )

        assert result is updated
        service.repository.update.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_update_local_to_remote_requires_usable_api_key(self, service):
        """Changing a no-auth row to a remote provider cannot leave a sentinel credential."""
        provider_id = uuid4()
        existing = MagicMock()
        existing.provider_type = ProviderType.OLLAMA
        existing.operation_type = OperationType.LLM
        existing.is_default = False
        existing.api_key_encrypted = "encrypted-no-key"
        service.repository.get_by_id.return_value = existing
        service.encryption_service = MagicMock()
        service.encryption_service.decrypt.return_value = NO_API_KEY_SENTINEL

        with pytest.raises(ProviderCredentialRequiredError, match="must be resubmitted"):
            await service.update_provider(
                provider_id,
                ProviderConfigUpdate(provider_type=ProviderType.OPENAI),
            )

        service.repository.update.assert_not_called()

    @pytest.mark.parametrize(
        "unsafe_config",
        [
            {"aws_secret_access_key": "secret"},
            {"access_token": "secret"},
            {"custom_unknown_option": "value"},
            {"transport": {"headers": {"Authorization": "Bearer secret"}}},
        ],
    )
    def test_provider_create_rejects_unstructured_or_private_config(
        self,
        unsafe_config,
    ):
        """New provider config can contain only fields in the positive public schema."""
        with pytest.raises(ValidationError):
            ProviderConfigCreate(
                name="unsafe-config",
                provider_type=ProviderType.OPENAI,
                api_key="sk-test",
                llm_model="gpt-4o",
                config=unsafe_config,
            )

    @pytest.mark.parametrize(
        "unsafe_config",
        [
            {"password": "secret"},
            {"oauth_token": "secret"},
            {"unknown": 1},
        ],
    )
    def test_provider_update_rejects_unstructured_or_private_config(
        self,
        unsafe_config,
    ):
        """Updates cannot introduce plaintext credentials or unknown JSON fields."""
        with pytest.raises(ValidationError):
            ProviderConfigUpdate(config=unsafe_config)

    def test_embedding_provider_options_use_positive_schema(self):
        """Structured embedding options reject arbitrary credential-bearing kwargs."""
        with pytest.raises(ValidationError):
            ProviderConfigCreate(
                name="unsafe-embedding-options",
                provider_type=ProviderType.OPENAI,
                operation_type=OperationType.EMBEDDING,
                api_key="sk-test",
                embedding_config=EmbeddingConfig(
                    model="text-embedding-3-small",
                    provider_options={"api_key": "nested-secret"},
                ),
            )

        config = ProviderConfigCreate(
            name="safe-embedding-options",
            provider_type=ProviderType.OPENAI,
            operation_type=OperationType.EMBEDDING,
            api_key="sk-test",
            embedding_config=EmbeddingConfig(
                model="text-embedding-3-small",
                provider_options={"batch_size": 32, "input_type": "search_document"},
            ),
        )
        assert config.embedding_config is not None
        assert config.embedding_config.provider_options == {
            "batch_size": 32,
            "input_type": "search_document",
        }

    @pytest.mark.parametrize("provider_type", [ProviderType.BEDROCK, ProviderType.VERTEX])
    def test_persistent_provider_rejects_types_without_structured_credentials(
        self,
        provider_type,
    ):
        """Bedrock and Vertex are not advertised as persistable without a secret store schema."""
        with pytest.raises(ValidationError, match="Persistent authentication is not available"):
            ProviderConfigCreate(
                name=f"unsupported-{provider_type.value}",
                provider_type=provider_type,
                api_key="credential",
                llm_model="model",
            )
        with pytest.raises(ValidationError, match="Persistent authentication is not available"):
            ProviderConfigUpdate(provider_type=provider_type)

    @pytest.mark.asyncio
    async def test_existing_unsupported_provider_cannot_be_updated(self, service):
        """Historical Bedrock rows cannot imply that persistent auth remains supported."""
        provider_id = uuid4()
        existing = MagicMock()
        existing.provider_type = ProviderType.BEDROCK
        service.repository.get_by_id.return_value = existing

        with pytest.raises(UnsupportedProviderAuthError):
            await service.update_provider(provider_id, ProviderConfigUpdate(name="renamed"))

        service.repository.update.assert_not_called()

    @pytest.mark.parametrize(
        "base_url",
        [
            "https://api.openai.com",
            "https://proxy.example/tenant-token",
            "https://api.openai.com/v1/secret-segment",
            "https://proxy.example/v1/token",
        ],
    )
    def test_provider_base_url_rejects_arbitrary_path_tokens(self, base_url):
        """Provider endpoints accept only exact, explicitly safe API base paths."""
        with pytest.raises(ValidationError, match="allowed API base path"):
            ProviderProbeRequest(
                name="unsafe-path",
                provider_type=ProviderType.OPENAI,
                api_key="sk-test",
                base_url=base_url,
            )

    @pytest.mark.asyncio
    async def test_unsupported_probe_returns_configuration_valid_without_network(self, service):
        """Unsupported probes validate the draft but do not pretend to contact the provider."""
        config = ProviderProbeRequest(
            name="azure-draft",
            provider_type=ProviderType.AZURE_OPENAI,
            api_key="sk-test",
            base_url="https://resource.openai.azure.com/v1",
        )

        with patch.object(service, "_check_provider_endpoint", new=AsyncMock()) as mock_check:
            validation = await service.test_provider_connection(config)

        assert validation.status == ProviderStatus.CONFIGURATION_VALID
        assert validation.probed is False
        assert validation.response_time_ms is None
        mock_check.assert_not_awaited()

    def test_unsupported_probe_still_validates_credential_and_url(self):
        """Skipping network I/O does not bypass draft credential or URL validation."""
        with pytest.raises(ValidationError, match="API key cannot be empty"):
            ProviderProbeRequest(
                name="azure-missing-key",
                provider_type=ProviderType.AZURE_OPENAI,
                base_url="https://resource.openai.azure.com/v1",
            )
        with pytest.raises(ValidationError, match="allowed API base path"):
            ProviderProbeRequest(
                name="azure-unsafe-path",
                provider_type=ProviderType.AZURE_OPENAI,
                api_key="sk-test",
                base_url="https://resource.openai.azure.com/deployment-token",
            )

    def test_anthropic_probe_path_is_idempotent(self, service):
        """An Anthropic /v1 base path is not duplicated by the models probe."""
        now = datetime.now(UTC)
        provider = ProviderConfig(
            id=uuid4(),
            name="anthropic",
            provider_type=ProviderType.ANTHROPIC,
            api_key_encrypted="",
            base_url="https://api.anthropic.com/v1",
            llm_model="claude-test",
            created_at=now,
            updated_at=now,
        )

        url, _headers = service._build_special_check_spec(
            "anthropic",
            provider.base_url,
            "sk-test",
            provider,
        )

        assert url == "https://api.anthropic.com/v1/models"

    @pytest.mark.asyncio
    async def test_rust_environment_record_projects_without_decrypting(self, service):
        """Python responses understand the structured environment record written by Rust."""
        now = datetime.now(UTC)
        provider = ProviderConfig(
            id=uuid4(),
            name="rust-env-openai",
            provider_type=ProviderType.OPENAI,
            api_key_encrypted="encrypted-no-key-sentinel",
            base_url="https://api.openai.com/v1",
            llm_model="gpt-4o",
            config={
                "auth_method": "environment",
                "environment_variable": "OPENAI_API_KEY",
            },
            created_at=now,
            updated_at=now,
        )
        service.repository.get_latest_health.return_value = None
        service.encryption_service = MagicMock()

        with patch.dict("os.environ", {"OPENAI_API_KEY": "sk-runtime-only"}):
            response = await service._provider_to_response(provider)

        assert response.auth_method == ProviderAuthMethod.ENVIRONMENT
        assert response.environment_variable == "OPENAI_API_KEY"
        assert response.credential_source == "environment"
        assert response.credential_configured is True
        assert response.api_key_masked == ""
        service.encryption_service.decrypt.assert_not_called()

    @pytest.mark.asyncio
    async def test_rust_environment_record_health_uses_runtime_value(self, service):
        """Persisted health probes resolve a Rust environment reference at call time."""
        now = datetime.now(UTC)
        provider = ProviderConfig(
            id=uuid4(),
            name="rust-env-openai",
            provider_type=ProviderType.OPENAI,
            api_key_encrypted="encrypted-no-key-sentinel",
            base_url="https://api.openai.com/v1",
            llm_model="gpt-4o",
            config={
                "auth_method": "environment",
                "environment_variable": "OPENAI_API_KEY",
            },
            created_at=now,
            updated_at=now,
        )
        service.repository.get_by_id.return_value = provider
        service.encryption_service = MagicMock()

        with (
            patch.dict("os.environ", {"OPENAI_API_KEY": "sk-runtime-only"}),
            patch.object(
                service,
                "_check_provider_endpoint",
                new=AsyncMock(return_value=("healthy", None)),
            ) as mock_check,
        ):
            health = await service.check_provider_health(provider.id)

        assert health.status == ProviderStatus.HEALTHY
        mock_check.assert_awaited_once_with(provider, "sk-runtime-only")
        service.encryption_service.decrypt.assert_not_called()

    @pytest.mark.asyncio
    async def test_rust_environment_record_health_fails_closed_without_value(self, service):
        """Missing environment values do not fall back to the encrypted sentinel."""
        now = datetime.now(UTC)
        provider = ProviderConfig(
            id=uuid4(),
            name="rust-env-openai",
            provider_type=ProviderType.OPENAI,
            api_key_encrypted="encrypted-no-key-sentinel",
            base_url="https://api.openai.com/v1",
            llm_model="gpt-4o",
            config={
                "auth_method": "environment",
                "environment_variable": "OPENAI_API_KEY",
            },
            created_at=now,
            updated_at=now,
        )
        service.repository.get_by_id.return_value = provider
        service.encryption_service = MagicMock()

        with (
            patch.dict("os.environ", {}, clear=True),
            patch.object(service, "_check_provider_endpoint", new=AsyncMock()) as mock_check,
        ):
            health = await service.check_provider_health(provider.id)

        assert health.status == ProviderStatus.UNHEALTHY
        mock_check.assert_not_awaited()
        service.encryption_service.decrypt.assert_not_called()
