"""Unit tests for the retrieval backend registry + factory."""

from __future__ import annotations

from unittest.mock import Mock

import pytest

from src.domain.model.retrieval_store import RetrievalStore
from src.infrastructure.retrieval.registry import (
    ENGINE_MEMSTACK_PGVECTOR,
    ENV_RETRIEVAL_STORE_ID_PREFIX,
    RetrievalBackendFactory,
    RetrievalBackendRegistry,
    env_retrieval_store_id,
    get_retrieval_backend_registry,
    register_env_default_retrieval_store,
    resolve_bound_retrieval_store_id,
)


@pytest.mark.unit
class TestRetrievalBackendRegistry:
    def test_register_and_get_engine(self) -> None:
        registry = RetrievalBackendRegistry()
        store = Mock()

        registry.register_engine(ENGINE_MEMSTACK_PGVECTOR, store)

        assert registry.get_by_engine(ENGINE_MEMSTACK_PGVECTOR) is store

    def test_register_store_upsert_semantics(self) -> None:
        registry = RetrievalBackendRegistry()
        first, second = Mock(), Mock()

        registry.register_store("store-1", first)
        registry.register_store("store-1", second)

        assert registry.get_by_store_id("store-1") is second

    def test_unregister_store_idempotent(self) -> None:
        registry = RetrievalBackendRegistry()
        store = Mock()
        registry.register_store("store-1", store)

        assert registry.unregister_store("store-1") is store
        assert registry.unregister_store("store-1") is None

    def test_env_store_id_prefix(self) -> None:
        store_id = env_retrieval_store_id(ENGINE_MEMSTACK_PGVECTOR)

        assert store_id.startswith(ENV_RETRIEVAL_STORE_ID_PREFIX)
        assert resolve_bound_retrieval_store_id(None) == store_id
        assert resolve_bound_retrieval_store_id("db-store-1") == "db-store-1"

    def test_many_stores_same_engine(self) -> None:
        registry = RetrievalBackendRegistry()
        first, second = Mock(), Mock()

        registry.register_store("store-a", first)
        registry.register_store("store-b", second)

        assert registry.get_by_store_id("store-a") is first
        assert registry.get_by_store_id("store-b") is second

    def test_global_singleton_and_env_registration(self) -> None:
        store = Mock()
        store_id = register_env_default_retrieval_store(store)

        registry = get_retrieval_backend_registry()
        assert registry.get_by_store_id(store_id) is store
        assert registry.get_by_engine(ENGINE_MEMSTACK_PGVECTOR) is store


@pytest.mark.unit
class TestRetrievalBackendFactory:
    def test_dispatch_builds_registered_engine(self) -> None:
        factory = RetrievalBackendFactory()
        built = Mock()
        factory.register_builder(ENGINE_MEMSTACK_PGVECTOR, lambda store: built)
        store = RetrievalStore(
            id="s",
            tenant_id="t",
            name="n",
            engine_type=ENGINE_MEMSTACK_PGVECTOR,
        )

        assert factory.build(store) is built

    def test_unknown_engine_raises(self) -> None:
        factory = RetrievalBackendFactory()
        store = RetrievalStore(id="s", tenant_id="t", name="n", engine_type="unknown")

        with pytest.raises(ValueError, match="Unsupported retrieval engine type"):
            factory.build(store)


@pytest.mark.unit
class TestRetrievalStoreMasking:
    def test_masked_connection_config_redacts_secrets(self) -> None:
        store = RetrievalStore(
            id="s",
            tenant_id="t",
            name="n",
            connection_config={
                "base_url": "https://weknora.example.com",
                "api_key": "k",
                "token": "tok",
                "authorization": "bearer tok",
            },
        )

        masked = store.masked_connection_config()

        assert masked["base_url"] == "https://weknora.example.com"
        assert masked["api_key"] == "***"
        assert masked["token"] == "***"
        assert masked["authorization"] == "***"

    def test_masked_connection_config_empty_secrets_not_masked(self) -> None:
        store = RetrievalStore(
            id="s",
            tenant_id="t",
            name="n",
            connection_config={"api_key": ""},
        )

        assert store.masked_connection_config()["api_key"] == ""
