"""Focused unit tests for provider credential persistence transitions."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.domain.llm_providers.models import (
    EmbeddingConfig,
    OperationType,
    ProviderConfigUpdate,
    ProviderType,
)
from src.infrastructure.llm.provider_credentials import NO_API_KEY_SENTINEL
from src.infrastructure.persistence.llm_providers_repository import SQLAlchemyProviderRepository


def test_apply_api_key_update_clears_remote_secret_when_switching_to_local() -> None:
    """A remote-to-local transition overwrites the old credential with the no-key sentinel."""
    encryption_service = MagicMock()
    encryption_service.encrypt.return_value = "encrypted-local-sentinel"
    with patch(
        "src.infrastructure.persistence.llm_providers_repository.get_encryption_service",
        return_value=encryption_service,
    ):
        repository = SQLAlchemyProviderRepository(session=MagicMock())
    orm = SimpleNamespace(provider_type=ProviderType.OPENAI.value, api_key_encrypted="old-secret")

    repository._apply_api_key_update(
        orm,
        ProviderConfigUpdate(provider_type=ProviderType.OLLAMA),
    )

    encryption_service.encrypt.assert_called_once_with(NO_API_KEY_SENTINEL)
    assert orm.api_key_encrypted == "encrypted-local-sentinel"


def test_apply_api_key_update_preserves_remote_secret_without_replacement() -> None:
    """Ordinary remote metadata updates do not rewrite encrypted credentials."""
    encryption_service = MagicMock()
    with patch(
        "src.infrastructure.persistence.llm_providers_repository.get_encryption_service",
        return_value=encryption_service,
    ):
        repository = SQLAlchemyProviderRepository(session=MagicMock())
    orm = SimpleNamespace(provider_type=ProviderType.OPENAI.value, api_key_encrypted="old-secret")

    repository._apply_api_key_update(orm, ProviderConfigUpdate(name="renamed"))

    encryption_service.encrypt.assert_not_called()
    assert orm.api_key_encrypted == "old-secret"


def test_apply_simple_field_updates_persists_explicit_base_url_clear() -> None:
    """Explicit empty endpoint input clears the stored custom endpoint."""
    with patch(
        "src.infrastructure.persistence.llm_providers_repository.get_encryption_service",
        return_value=MagicMock(),
    ):
        repository = SQLAlchemyProviderRepository(session=MagicMock())
    orm = SimpleNamespace(base_url="https://proxy.example/v1")
    update = ProviderConfigUpdate(base_url="")

    repository._apply_simple_field_updates(orm, update)

    assert "base_url" in update.model_fields_set
    assert update.base_url is None
    assert orm.base_url is None


def test_embedding_config_update_replaces_public_model_and_preserves_private_metadata() -> None:
    """A standalone embedding snapshot must not inherit the legacy model column."""
    with patch(
        "src.infrastructure.persistence.llm_providers_repository.get_encryption_service",
        return_value=MagicMock(),
    ):
        repository = SQLAlchemyProviderRepository(session=MagicMock())
    orm = SimpleNamespace(embedding_model="text-embedding-3-small")
    updated_config = {
        "embedding": {
            "model": "text-embedding-3-small",
            "dimensions": 1536,
            "private_metadata": {"lineage": "must-survive"},
            "provider_options": {
                "batch_size": 8,
                "private_token": "must-survive",
            },
        }
    }

    repository._apply_embedding_config_update(
        orm,
        ProviderConfigUpdate(
            embedding_config=EmbeddingConfig(
                dimensions=2048,
                provider_options={"batch_size": 16},
            )
        ),
        updated_config,
    )

    assert orm.embedding_model is None
    assert updated_config == {
        "embedding": {
            "dimensions": 2048,
            "private_metadata": {"lineage": "must-survive"},
            "provider_options": {
                "batch_size": 16,
                "private_token": "must-survive",
            },
        }
    }


@pytest.mark.asyncio
async def test_default_operation_lock_is_noop_for_non_postgresql() -> None:
    """SQLite-backed tests safely degrade without issuing PostgreSQL functions."""
    session = MagicMock()
    session.get_bind.return_value.dialect.name = "sqlite"
    session.execute = AsyncMock()
    with patch(
        "src.infrastructure.persistence.llm_providers_repository.get_encryption_service",
        return_value=MagicMock(),
    ):
        repository = SQLAlchemyProviderRepository(session=session)

    await repository._acquire_default_operation_lock(session, OperationType.LLM)

    session.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_default_operation_lock_uses_postgresql_transaction_advisory_lock() -> None:
    """Default create and update share one operation-scoped transaction lock."""
    session = MagicMock()
    session.get_bind.return_value.dialect.name = "postgresql"
    session.execute = AsyncMock()
    with patch(
        "src.infrastructure.persistence.llm_providers_repository.get_encryption_service",
        return_value=MagicMock(),
    ):
        repository = SQLAlchemyProviderRepository(session=session)

    await repository._acquire_default_operation_lock(session, OperationType.EMBEDDING)

    session.execute.assert_awaited_once()
    statement = session.execute.await_args.args[0]
    assert "pg_advisory_xact_lock" in str(statement)
