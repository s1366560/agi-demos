"""
Integration tests for SQLAlchemy Provider Repository.

Tests repository operations with real database.
"""

import pytest

from src.domain.llm_providers.models import (
    EmbeddingConfig,
    LLMUsageLogCreate,
    NoActiveProviderError,
    OperationType,
    ProviderConfigCreate,
    ProviderConfigUpdate,
    ProviderRevisionConflictError,
    ProviderStatus,
    ProviderType,
    provider_revision,
)
from src.infrastructure.persistence.llm_providers_models import LLMProvider as LLMProviderORM
from src.infrastructure.persistence.llm_providers_repository import SQLAlchemyProviderRepository


class TestProviderRepository:
    """Test suite for SQLAlchemyProviderRepository."""

    @pytest.mark.asyncio
    async def test_create_provider(self, db_session):
        """Test creating a provider."""
        repository = SQLAlchemyProviderRepository(session=db_session)

        config = ProviderConfigCreate(
            name="test-openai",
            provider_type=ProviderType.OPENAI,
            api_key="sk-test-key-12345",
            llm_model="gpt-4o",
            llm_small_model="gpt-4o-mini",
            embedding_model="text-embedding-3-small",
        )

        provider = await repository.create(config)

        assert provider.id is not None
        assert provider.name == "test-openai"
        assert provider.provider_type == ProviderType.OPENAI
        assert provider.api_key_encrypted is not None
        assert provider.llm_model == "gpt-4o"
        assert provider.embedding_model is None
        assert provider.is_active is True
        assert provider.is_default is False

    @pytest.mark.asyncio
    async def test_create_provider_persists_embedding_config(self, db_session):
        """Test structured embedding config is persisted and hydrated."""
        repository = SQLAlchemyProviderRepository(session=db_session)

        config = ProviderConfigCreate(
            name="test-openai-embedding-config",
            provider_type=ProviderType.OPENAI,
            operation_type=OperationType.EMBEDDING,
            api_key="sk-test-key-12345",
            embedding_config=EmbeddingConfig(
                model="text-embedding-3-large",
                dimensions=1024,
                encoding_format="float",
                user="tenant-a",
                timeout=9.5,
                provider_options={"batch_size": 32},
            ),
        )

        provider = await repository.create(config)

        assert provider.embedding_model == "text-embedding-3-large"
        assert provider.embedding_config is not None
        assert provider.embedding_config.model == "text-embedding-3-large"
        assert provider.embedding_config.dimensions == 1024
        assert provider.embedding_config.user == "tenant-a"

        stored_embedding = provider.config.get("embedding", {})
        assert stored_embedding.get("model") == "text-embedding-3-large"
        assert stored_embedding.get("dimensions") == 1024
        assert stored_embedding.get("batch_size") is None
        assert stored_embedding.get("provider_options", {}).get("batch_size") == 32

    @pytest.mark.asyncio
    async def test_create_default_atomically_replaces_only_same_operation_default(self, db_session):
        """Creating a default clears and revises the previous operation default."""
        repository = SQLAlchemyProviderRepository(session=db_session)
        previous_default = await repository.create(
            ProviderConfigCreate(
                name="previous-default-before-create",
                provider_type=ProviderType.OPENAI,
                api_key="sk-test-previous-create",
                llm_model="gpt-4o",
                is_default=True,
            )
        )
        embedding_default = await repository.create(
            ProviderConfigCreate(
                name="embedding-default-before-create",
                provider_type=ProviderType.OPENAI,
                operation_type=OperationType.EMBEDDING,
                api_key="sk-test-embedding-create",
                embedding_model="text-embedding-3-small",
                is_default=True,
            )
        )

        created = await repository.create(
            ProviderConfigCreate(
                name="new-default-from-create",
                provider_type=ProviderType.OPENAI,
                api_key="sk-test-new-create",
                llm_model="gpt-4o-mini",
                is_default=True,
            )
        )

        assert created.is_default is True
        db_session.expire_all()
        persisted_previous = await repository.get_by_id(previous_default.id)
        persisted_embedding = await repository.get_by_id(embedding_default.id)
        assert persisted_previous is not None
        assert persisted_previous.is_default is False
        assert provider_revision(persisted_previous.updated_at) > provider_revision(
            previous_default.updated_at
        )
        assert persisted_embedding is not None
        assert persisted_embedding.is_default is True
        assert provider_revision(persisted_embedding.updated_at) == provider_revision(
            embedding_default.updated_at
        )

    @pytest.mark.asyncio
    async def test_create_default_name_conflict_does_not_clear_current_default(self, db_session):
        """An idempotent name conflict must not remove the existing default."""
        repository = SQLAlchemyProviderRepository(session=db_session)
        current_default = await repository.create(
            ProviderConfigCreate(
                name="current-default-before-name-conflict",
                provider_type=ProviderType.OPENAI,
                api_key="sk-test-current-conflict",
                llm_model="gpt-4o",
                is_default=True,
            )
        )
        existing_non_default = await repository.create(
            ProviderConfigCreate(
                name="existing-name-conflict-target",
                provider_type=ProviderType.OPENAI,
                api_key="sk-test-existing-conflict",
                llm_model="gpt-4o-mini",
            )
        )

        returned = await repository.create(
            ProviderConfigCreate(
                name=existing_non_default.name,
                provider_type=ProviderType.OPENAI,
                api_key="sk-test-ignored-conflict",
                llm_model="gpt-4o-mini",
                is_default=True,
            )
        )

        assert returned.id == existing_non_default.id
        assert returned.is_default is False
        db_session.expire_all()
        persisted_default = await repository.get_by_id(current_default.id)
        assert persisted_default is not None
        assert persisted_default.is_default is True

    @pytest.mark.asyncio
    async def test_get_provider_by_id(self, db_session):
        """Test retrieving provider by ID."""
        repository = SQLAlchemyProviderRepository(session=db_session)

        config = ProviderConfigCreate(
            name="test-provider",
            provider_type=ProviderType.OPENAI,
            api_key="sk-test",
            llm_model="gpt-4o",
        )

        created = await repository.create(config)
        retrieved = await repository.get_by_id(created.id)

        assert retrieved is not None
        assert retrieved.id == created.id
        assert retrieved.name == "test-provider"

    @pytest.mark.asyncio
    async def test_get_provider_by_name(self, db_session):
        """Test retrieving provider by name."""
        repository = SQLAlchemyProviderRepository(session=db_session)

        config = ProviderConfigCreate(
            name="unique-provider",
            provider_type=ProviderType.OPENAI,
            api_key="sk-test",
            llm_model="gpt-4o",
        )

        await repository.create(config)
        retrieved = await repository.get_by_name("unique-provider")

        assert retrieved is not None
        assert retrieved.name == "unique-provider"

    @pytest.mark.asyncio
    async def test_list_all_providers(self, db_session):
        """Test listing all providers."""
        repository = SQLAlchemyProviderRepository(session=db_session)

        # Create multiple providers
        for i in range(3):
            config = ProviderConfigCreate(
                name=f"provider-{i}",
                provider_type=ProviderType.OPENAI,
                api_key=f"sk-test-{i}",
                llm_model="gpt-4o",
                is_active=True,
            )
            await repository.create(config)

        # Create inactive provider
        inactive_config = ProviderConfigCreate(
            name="inactive-provider",
            provider_type=ProviderType.OPENAI,
            api_key="sk-test-inactive",
            llm_model="gpt-4o",
            is_active=False,
        )
        await repository.create(inactive_config)

        # List active only
        active_providers = await repository.list_all(include_inactive=False)
        assert len(active_providers) == 3

        # List all
        all_providers = await repository.list_all(include_inactive=True)
        assert len(all_providers) == 4

    @pytest.mark.asyncio
    async def test_update_provider(self, db_session):
        """Test updating provider."""
        repository = SQLAlchemyProviderRepository(session=db_session)

        config = ProviderConfigCreate(
            name="original-name",
            provider_type=ProviderType.OPENAI,
            api_key="sk-test",
            llm_model="gpt-4o",
        )

        created = await repository.create(config)

        # Update provider
        update = ProviderConfigUpdate(
            expected_revision=provider_revision(created.updated_at),
            name="updated-name",
            llm_model="gpt-4o-turbo",
        )

        updated = await repository.update(created.id, update)

        assert updated is not None
        assert updated.name == "updated-name"
        assert updated.llm_model == "gpt-4o-turbo"
        assert provider_revision(updated.updated_at) > provider_revision(created.updated_at)

        with pytest.raises(ProviderRevisionConflictError):
            await repository.update(
                created.id,
                ProviderConfigUpdate(
                    expected_revision=provider_revision(created.updated_at),
                    name="stale-write",
                ),
            )

    @pytest.mark.asyncio
    async def test_stale_default_switch_has_no_side_effects(self, db_session):
        """A stale target revision must not clear the current operation default."""
        repository = SQLAlchemyProviderRepository(session=db_session)
        current_default = await repository.create(
            ProviderConfigCreate(
                name="current-default-stale-switch",
                provider_type=ProviderType.OPENAI,
                api_key="sk-test-current-default",
                llm_model="gpt-4o",
                is_default=True,
            )
        )
        target = await repository.create(
            ProviderConfigCreate(
                name="target-stale-switch",
                provider_type=ProviderType.OPENAI,
                api_key="sk-test-target",
                llm_model="gpt-4o-mini",
            )
        )
        stale_revision = provider_revision(target.updated_at)
        fresh_target = await repository.update(
            target.id,
            ProviderConfigUpdate(name="target-stale-switch-fresh"),
        )
        assert fresh_target is not None

        with pytest.raises(ProviderRevisionConflictError):
            await repository.update(
                target.id,
                ProviderConfigUpdate(
                    expected_revision=stale_revision,
                    is_default=True,
                ),
                replace_default_for=OperationType.LLM,
            )

        await db_session.rollback()
        db_session.expire_all()
        persisted_default = await repository.get_by_id(current_default.id)
        persisted_target = await repository.get_by_id(target.id)

        assert persisted_default is not None
        assert persisted_default.is_default is True
        assert provider_revision(persisted_default.updated_at) == provider_revision(
            current_default.updated_at
        )
        assert persisted_target is not None
        assert persisted_target.name == "target-stale-switch-fresh"
        assert persisted_target.is_default is False

    @pytest.mark.asyncio
    async def test_default_switch_updates_target_and_previous_default_atomically(self, db_session):
        """A successful switch replaces only the default for the requested operation."""
        repository = SQLAlchemyProviderRepository(session=db_session)
        previous_default = await repository.create(
            ProviderConfigCreate(
                name="previous-llm-default",
                provider_type=ProviderType.OPENAI,
                api_key="sk-test-previous-default",
                llm_model="gpt-4o",
                is_default=True,
            )
        )
        embedding_default = await repository.create(
            ProviderConfigCreate(
                name="embedding-default-during-llm-switch",
                provider_type=ProviderType.OPENAI,
                operation_type=OperationType.EMBEDDING,
                api_key="sk-test-embedding-default",
                embedding_model="text-embedding-3-small",
                is_default=True,
            )
        )
        target = await repository.create(
            ProviderConfigCreate(
                name="new-llm-default",
                provider_type=ProviderType.OPENAI,
                api_key="sk-test-new-default",
                llm_model="gpt-4o-mini",
            )
        )

        updated = await repository.update(
            target.id,
            ProviderConfigUpdate(
                expected_revision=provider_revision(target.updated_at),
                is_default=True,
            ),
            replace_default_for=OperationType.LLM,
        )

        assert updated is not None
        assert updated.is_default is True
        db_session.expire_all()
        persisted_previous = await repository.get_by_id(previous_default.id)
        persisted_embedding = await repository.get_by_id(embedding_default.id)

        assert persisted_previous is not None
        assert persisted_previous.is_default is False
        assert provider_revision(persisted_previous.updated_at) > provider_revision(
            previous_default.updated_at
        )
        assert persisted_embedding is not None
        assert persisted_embedding.is_default is True
        assert provider_revision(persisted_embedding.updated_at) == provider_revision(
            embedding_default.updated_at
        )

    @pytest.mark.asyncio
    async def test_update_provider_embedding_config_merges_model(self, db_session):
        """An explicitly resubmitted model is stored with the embedding snapshot."""
        repository = SQLAlchemyProviderRepository(session=db_session)

        created = await repository.create(
            ProviderConfigCreate(
                name="provider-update-embedding-config",
                provider_type=ProviderType.OPENAI,
                operation_type=OperationType.EMBEDDING,
                api_key="sk-test",
                embedding_model="text-embedding-3-small",
            )
        )

        updated = await repository.update(
            created.id,
            ProviderConfigUpdate(
                embedding_model="text-embedding-3-small",
                embedding_config=EmbeddingConfig(dimensions=1536, timeout=4.0),
            ),
        )

        assert updated is not None
        assert updated.embedding_model == "text-embedding-3-small"
        assert updated.embedding_config is not None
        assert updated.embedding_config.model == "text-embedding-3-small"
        assert updated.embedding_config.dimensions == 1536

    @pytest.mark.asyncio
    async def test_public_config_update_preserves_hidden_historical_fields(self, db_session):
        """A public config snapshot replaces safe fields without erasing hidden metadata."""
        repository = SQLAlchemyProviderRepository(session=db_session)
        created = await repository.create(
            ProviderConfigCreate(
                name="provider-safe-config-merge",
                provider_type=ProviderType.OPENAI,
                operation_type=OperationType.EMBEDDING,
                api_key="sk-test",
                embedding_model="text-embedding-3-small",
                config={"temperature": 0.2, "max_tokens": 1024},
            )
        )
        orm = await db_session.get(LLMProviderORM, created.id)
        assert orm is not None
        orm.config = {
            "temperature": 0.2,
            "max_tokens": 1024,
            "historical_private_field": "must-survive",
            "auth_method": "environment",
            "environment_variable": "OPENAI_API_KEY",
            "retries": {"max_attempts": 4, "private_retry_token": "must-survive"},
            "transport": {
                "connect_timeout_seconds": 5,
                "headers": {"Authorization": "must-survive"},
            },
            "embedding": {
                "dimensions": 1536,
                "private_embedding_field": "must-survive",
                "provider_options": {
                    "batch_size": 8,
                    "private_provider_token": "must-survive",
                },
            },
        }
        await db_session.commit()

        updated = await repository.update(
            created.id,
            ProviderConfigUpdate(
                config={"temperature": 0.7},
                embedding_config=EmbeddingConfig(
                    dimensions=2048,
                    provider_options={"batch_size": 16},
                ),
            ),
        )

        assert updated is not None
        assert updated.config == {
            "temperature": 0.7,
            "historical_private_field": "must-survive",
            "auth_method": "environment",
            "environment_variable": "OPENAI_API_KEY",
            "retries": {"private_retry_token": "must-survive"},
            "transport": {"headers": {"Authorization": "must-survive"}},
            "embedding": {
                "dimensions": 2048,
                "private_embedding_field": "must-survive",
                "provider_options": {
                    "batch_size": 16,
                    "private_provider_token": "must-survive",
                },
            },
        }

    @pytest.mark.asyncio
    async def test_standalone_embedding_update_replaces_safe_fields_and_preserves_private_metadata(
        self,
        db_session,
    ):
        """Structured embedding updates replace their public snapshot at every nested level."""
        repository = SQLAlchemyProviderRepository(session=db_session)
        created = await repository.create(
            ProviderConfigCreate(
                name="provider-standalone-embedding-safe-merge",
                provider_type=ProviderType.OPENAI,
                operation_type=OperationType.EMBEDDING,
                api_key="sk-test",
                embedding_model="text-embedding-3-small",
            )
        )
        orm = await db_session.get(LLMProviderORM, created.id)
        assert orm is not None
        orm.config = {
            "embedding": {
                "model": "text-embedding-3-small",
                "dimensions": 1536,
                "encoding_format": "float",
                "timeout": 8.0,
                "private_embedding_metadata": {"lineage": "must-survive"},
                "provider_options": {
                    "batch_size": 8,
                    "input_type": "search_document",
                    "private_provider_token": "must-survive",
                },
            }
        }
        await db_session.commit()

        updated = await repository.update(
            created.id,
            ProviderConfigUpdate(
                embedding_config=EmbeddingConfig(
                    dimensions=2048,
                    provider_options={"batch_size": 16},
                )
            ),
        )

        assert updated is not None
        assert updated.embedding_model is None
        assert updated.config == {
            "embedding": {
                "dimensions": 2048,
                "private_embedding_metadata": {"lineage": "must-survive"},
                "provider_options": {
                    "batch_size": 16,
                    "private_provider_token": "must-survive",
                },
            }
        }

    @pytest.mark.asyncio
    async def test_empty_embedding_update_clears_only_safe_fields(self, db_session):
        """An explicit empty embedding object cannot erase historical private metadata."""
        repository = SQLAlchemyProviderRepository(session=db_session)
        created = await repository.create(
            ProviderConfigCreate(
                name="provider-empty-embedding-safe-merge",
                provider_type=ProviderType.OPENAI,
                operation_type=OperationType.EMBEDDING,
                api_key="sk-test",
                embedding_model="text-embedding-3-small",
            )
        )
        orm = await db_session.get(LLMProviderORM, created.id)
        assert orm is not None
        orm.config = {
            "embedding": {
                "model": "text-embedding-3-small",
                "dimensions": 1536,
                "timeout": 8.0,
                "private_embedding_metadata": "must-survive",
                "provider_options": {
                    "batch_size": 8,
                    "private_provider_token": "must-survive",
                },
            }
        }
        await db_session.commit()

        updated = await repository.update(
            created.id,
            ProviderConfigUpdate.model_validate({"embedding_config": {}}),
        )

        assert updated is not None
        assert updated.embedding_model is None
        assert updated.config == {
            "embedding": {
                "private_embedding_metadata": "must-survive",
                "provider_options": {"private_provider_token": "must-survive"},
            }
        }

    @pytest.mark.asyncio
    async def test_delete_provider_soft_delete(self, db_session):
        """Test that deletion is a soft delete."""
        repository = SQLAlchemyProviderRepository(session=db_session)

        config = ProviderConfigCreate(
            name="to-delete",
            provider_type=ProviderType.OPENAI,
            api_key="sk-test",
            llm_model="gpt-4o",
        )

        created = await repository.create(config)
        assert created.is_active is True

        # Delete
        success = await repository.delete(created.id)
        assert success is True

        # Verify soft delete (still in DB but inactive)
        deleted = await repository.get_by_id(created.id)
        assert deleted is not None
        assert deleted.is_active is False

        # Should not appear in active list
        active = await repository.list_active()
        assert deleted not in active

    @pytest.mark.asyncio
    async def test_find_default_provider(self, db_session):
        """Test finding default provider."""
        repository = SQLAlchemyProviderRepository(session=db_session)

        # Create non-default provider
        config1 = ProviderConfigCreate(
            name="regular-provider",
            provider_type=ProviderType.OPENAI,
            api_key="sk-test",
            llm_model="gpt-4o",
            is_default=False,
        )
        await repository.create(config1)

        # Create default provider
        config2 = ProviderConfigCreate(
            name="default-provider",
            provider_type=ProviderType.OPENAI,
            api_key="sk-test",
            llm_model="gpt-4o",
            is_default=True,
        )
        await repository.create(config2)

        # Find default
        default = await repository.find_default_provider()
        assert default is not None
        assert default.name == "default-provider"
        assert default.is_default is True

    @pytest.mark.asyncio
    async def test_find_first_active_provider(self, db_session):
        """Test finding first active provider."""
        repository = SQLAlchemyProviderRepository(session=db_session)

        # Create providers in specific order
        for i in range(3):
            config = ProviderConfigCreate(
                name=f"provider-{i}",
                provider_type=ProviderType.OPENAI,
                api_key=f"sk-test-{i}",
                llm_model="gpt-4o",
                is_active=True,
            )
            await repository.create(config)

        # Find first active
        first = await repository.find_first_active_provider()
        assert first is not None
        assert first.name == "provider-0"  # First created

    @pytest.mark.asyncio
    async def test_tenant_provider_assignment(self, db_session):
        """Test assigning provider to tenant."""
        repository = SQLAlchemyProviderRepository(session=db_session)

        # Create provider
        config = ProviderConfigCreate(
            name="tenant-provider",
            provider_type=ProviderType.OPENAI,
            api_key="sk-test",
            llm_model="gpt-4o",
        )
        provider = await repository.create(config)

        # Assign to tenant
        tenant_id = "tenant-123"
        mapping = await repository.assign_provider_to_tenant(
            tenant_id=tenant_id,
            provider_id=provider.id,
            priority=0,
        )

        assert mapping.tenant_id == tenant_id
        assert mapping.provider_id == provider.id
        assert mapping.priority == 0

        # Verify retrieval
        tenant_providers = await repository.get_tenant_providers(tenant_id)
        assert len(tenant_providers) == 1
        assert tenant_providers[0].provider_id == provider.id

    @pytest.mark.asyncio
    async def test_find_tenant_provider(self, db_session):
        """Test finding tenant-specific provider."""
        repository = SQLAlchemyProviderRepository(session=db_session)

        # Create provider
        config = ProviderConfigCreate(
            name="tenant-specific",
            provider_type=ProviderType.OPENAI,
            api_key="sk-test",
            llm_model="gpt-4o",
        )
        provider = await repository.create(config)

        # Assign to tenant
        tenant_id = "tenant-456"
        await repository.assign_provider_to_tenant(tenant_id, provider.id, priority=0)

        # Find tenant provider
        found = await repository.find_tenant_provider(tenant_id)
        assert found is not None
        assert found.id == provider.id

    @pytest.mark.asyncio
    async def test_find_tenant_provider_by_operation_type(self, db_session):
        """Test operation-specific tenant provider resolution."""
        repository = SQLAlchemyProviderRepository(session=db_session)

        llm_provider = await repository.create(
            ProviderConfigCreate(
                name="tenant-llm-provider",
                provider_type=ProviderType.OPENAI,
                api_key="sk-test-llm",
                llm_model="gpt-4o",
            )
        )
        embedding_provider = await repository.create(
            ProviderConfigCreate(
                name="tenant-embedding-provider",
                provider_type=ProviderType.DASHSCOPE_EMBEDDING,
                operation_type=OperationType.EMBEDDING,
                api_key="sk-test-embedding",
                embedding_model="text-embedding-v3",
            )
        )

        tenant_id = "tenant-op-routing"
        await repository.assign_provider_to_tenant(
            tenant_id,
            llm_provider.id,
            priority=0,
            operation_type=OperationType.LLM,
        )
        await repository.assign_provider_to_tenant(
            tenant_id,
            embedding_provider.id,
            priority=0,
            operation_type=OperationType.EMBEDDING,
        )

        llm_found = await repository.find_tenant_provider(tenant_id, OperationType.LLM)
        embedding_found = await repository.find_tenant_provider(tenant_id, OperationType.EMBEDDING)
        rerank_fallback = await repository.find_tenant_provider(tenant_id, OperationType.RERANK)

        assert llm_found is not None
        assert embedding_found is not None
        assert rerank_fallback is None
        assert llm_found.id == llm_provider.id
        assert embedding_found.id == embedding_provider.id
        # Operation roles are isolated: no rerank-specific mapping means no provider.

    @pytest.mark.asyncio
    async def test_resolve_provider_hierarchy(self, db_session):
        """Test provider resolution hierarchy: tenant -> default -> first active."""
        repository = SQLAlchemyProviderRepository(session=db_session)

        # Scenario 1: Tenant-specific provider
        tenant_provider = ProviderConfigCreate(
            name="tenant-provider",
            provider_type=ProviderType.OPENAI,
            api_key="sk-test",
            llm_model="gpt-4o",
        )
        tp = await repository.create(tenant_provider)
        await repository.assign_provider_to_tenant("tenant-1", tp.id, priority=0)

        resolved = await repository.resolve_provider(tenant_id="tenant-1")
        assert resolved.provider.id == tp.id
        assert resolved.resolution_source == "tenant"

        # Scenario 2: Default provider (no tenant-specific)
        default_provider = ProviderConfigCreate(
            name="default-provider",
            provider_type=ProviderType.OPENAI,
            api_key="sk-test",
            llm_model="gpt-4o",
            is_default=True,
        )
        dp = await repository.create(default_provider)

        resolved = await repository.resolve_provider(tenant_id="tenant-2")
        assert resolved.provider.id == dp.id
        assert resolved.resolution_source == "default"

        # Scenario 3: First active provider (no tenant, no default)
        # Note: Since we created a default provider in Scenario 2,
        # it will still be returned as "default" for tenant-3
        another_tenant = "tenant-3"
        resolved = await repository.resolve_provider(tenant_id=another_tenant)
        assert resolved.resolution_source == "default"  # Should be default, not fallback
        assert resolved.provider.is_default is True  # Should be the default provider
        assert resolved.provider.is_active is True

    @pytest.mark.asyncio
    async def test_create_local_provider_without_api_key(self, db_session):
        """Local providers should be creatable without API key."""
        repository = SQLAlchemyProviderRepository(session=db_session)

        provider = await repository.create(
            ProviderConfigCreate(
                name="local-ollama-provider",
                provider_type=ProviderType.OLLAMA,
                api_key="",
                llm_model="llama3.1:8b",
            )
        )

        assert provider.id is not None
        assert provider.provider_type == ProviderType.OLLAMA

    @pytest.mark.asyncio
    async def test_resolve_provider_no_active_providers(self, db_session):
        """Test that resolution fails when no active providers exist."""
        repository = SQLAlchemyProviderRepository(session=db_session)

        # Create inactive provider
        config = ProviderConfigCreate(
            name="inactive",
            provider_type=ProviderType.OPENAI,
            api_key="sk-test",
            llm_model="gpt-4o",
            is_active=False,
        )
        await repository.create(config)

        # Should raise error
        with pytest.raises(NoActiveProviderError):
            await repository.resolve_provider()

    @pytest.mark.asyncio
    async def test_unassign_provider_from_tenant(self, db_session):
        """Test unassigning provider from tenant."""
        repository = SQLAlchemyProviderRepository(session=db_session)

        # Create and assign provider
        config = ProviderConfigCreate(
            name="to-unassign",
            provider_type=ProviderType.OPENAI,
            api_key="sk-test",
            llm_model="gpt-4o",
        )
        provider = await repository.create(config)

        tenant_id = "tenant-789"
        await repository.assign_provider_to_tenant(tenant_id, provider.id, priority=0)

        # Unassign
        success = await repository.unassign_provider_from_tenant(tenant_id, provider.id)
        assert success is True

        # Verify unassigned
        tenant_providers = await repository.get_tenant_providers(tenant_id)
        assert len(tenant_providers) == 0

        # Should not find tenant provider anymore
        found = await repository.find_tenant_provider(tenant_id)
        assert found is None

    @pytest.mark.asyncio
    async def test_health_check_create_and_retrieve(self, db_session):
        """Test creating and retrieving health checks."""
        repository = SQLAlchemyProviderRepository(session=db_session)

        # Create provider
        config = ProviderConfigCreate(
            name="health-test",
            provider_type=ProviderType.OPENAI,
            api_key="sk-test",
            llm_model="gpt-4o",
        )
        provider = await repository.create(config)

        # Create health check
        from src.domain.llm_providers.models import ProviderHealthCreate

        health = ProviderHealthCreate(
            provider_id=provider.id,
            status=ProviderStatus.HEALTHY,
            response_time_ms=150,
        )

        created = await repository.create_health_check(health)
        assert created.provider_id == provider.id
        assert created.status == ProviderStatus.HEALTHY
        assert created.response_time_ms == 150

        # Retrieve latest health
        latest = await repository.get_latest_health(provider.id)
        assert latest is not None
        assert latest.status == ProviderStatus.HEALTHY

    @pytest.mark.asyncio
    async def test_usage_logging_and_statistics(self, db_session):
        """Test usage logging and statistics aggregation."""
        repository = SQLAlchemyProviderRepository(session=db_session)

        # Create provider
        config = ProviderConfigCreate(
            name="usage-test",
            provider_type=ProviderType.OPENAI,
            api_key="sk-test",
            llm_model="gpt-4o",
        )
        provider = await repository.create(config)

        # Create usage logs
        tenant_id = "tenant-stats"
        for i in range(3):
            log = LLMUsageLogCreate(
                provider_id=provider.id,
                tenant_id=tenant_id,
                operation_type=OperationType.LLM,
                model_name="gpt-4o",
                prompt_tokens=100 + i * 10,
                completion_tokens=50 + i * 5,
                cost_usd=0.001 + i * 0.0001,
            )
            await repository.create_usage_log(log)

        # Get statistics
        stats = await repository.get_usage_statistics(
            provider_id=provider.id,
            tenant_id=tenant_id,
        )

        assert len(stats) == 1
        assert stats[0].total_requests == 3
        assert stats[0].total_prompt_tokens == 330  # 100 + 110 + 120
        assert stats[0].total_completion_tokens == 165  # 50 + 55 + 60
        assert stats[0].total_tokens == 495

    @pytest.mark.asyncio
    async def test_api_key_encryption_decryption(self, db_session):
        """Test that API keys are encrypted at rest and can be decrypted."""
        import src.infrastructure.security.encryption_service as enc_module
        from src.infrastructure.security.encryption_service import EncryptionService

        # Save original function reference to restore later
        original_get_encryption_service = enc_module.get_encryption_service

        try:
            # Reset encryption service singleton and restore the real get_encryption_service
            # This is necessary because unit tests may have replaced get_encryption_service
            enc_module._encryption_service = None
            real_encryption_service = EncryptionService()
            enc_module._encryption_service = real_encryption_service
            enc_module.get_encryption_service = lambda: enc_module._encryption_service

            # Now create repository - it will use the same singleton we just created
            repository = SQLAlchemyProviderRepository(session=db_session)

            original_key = "sk-test-secret-key-12345"

            config = ProviderConfigCreate(
                name="encryption-test",
                provider_type=ProviderType.OPENAI,
                api_key=original_key,
                llm_model="gpt-4o",
            )

            provider = await repository.create(config)

            # Verify encrypted value is different from original
            assert provider.api_key_encrypted != original_key

            # Verify we can decrypt it
            decrypted_key = real_encryption_service.decrypt(provider.api_key_encrypted)
            assert decrypted_key == original_key
        finally:
            # Restore original function reference for other tests
            enc_module.get_encryption_service = original_get_encryption_service
            enc_module._encryption_service = None

    @pytest.mark.asyncio
    async def test_multiple_tenant_priority_ordering(self, db_session):
        """Test that tenant providers are ordered by priority."""
        repository = SQLAlchemyProviderRepository(session=db_session)

        tenant_id = "priority-tenant"

        # Create 3 providers
        providers = []
        for i in range(3):
            config = ProviderConfigCreate(
                name=f"priority-provider-{i}",
                provider_type=ProviderType.OPENAI,
                api_key=f"sk-test-{i}",
                llm_model="gpt-4o",
            )
            provider = await repository.create(config)
            providers.append(provider)

        # Assign with different priorities (out of order)
        await repository.assign_provider_to_tenant(tenant_id, providers[2].id, priority=2)
        await repository.assign_provider_to_tenant(tenant_id, providers[0].id, priority=0)
        await repository.assign_provider_to_tenant(tenant_id, providers[1].id, priority=1)

        # Get tenant providers - should be ordered by priority
        tenant_providers = await repository.get_tenant_providers(tenant_id)

        assert len(tenant_providers) == 3
        assert tenant_providers[0].provider_id == providers[0].id
        assert tenant_providers[1].provider_id == providers[1].id
        assert tenant_providers[2].provider_id == providers[2].id

    @pytest.mark.asyncio
    async def test_update_provider_api_key(self, db_session):
        """Test updating provider API key."""
        import src.infrastructure.security.encryption_service as enc_module
        from src.infrastructure.security.encryption_service import EncryptionService

        # Save original function reference to restore later
        original_get_encryption_service = enc_module.get_encryption_service

        try:
            # Reset encryption service singleton and restore the real get_encryption_service
            enc_module._encryption_service = None
            real_encryption_service = EncryptionService()
            enc_module._encryption_service = real_encryption_service
            enc_module.get_encryption_service = lambda: enc_module._encryption_service

            repository = SQLAlchemyProviderRepository(session=db_session)

            config = ProviderConfigCreate(
                name="key-update-test",
                provider_type=ProviderType.OPENAI,
                api_key="sk-original-key",
                llm_model="gpt-4o",
            )

            provider = await repository.create(config)

            # Update API key
            update = ProviderConfigUpdate(api_key="sk-new-key")
            updated = await repository.update(provider.id, update)

            assert updated is not None
            decrypted_key = real_encryption_service.decrypt(updated.api_key_encrypted)
            assert decrypted_key == "sk-new-key"
        finally:
            # Restore original function reference for other tests
            enc_module.get_encryption_service = original_get_encryption_service
            enc_module._encryption_service = None
