"""Unit tests for the graph backend registry + factory."""

from __future__ import annotations

from unittest.mock import Mock

import pytest

from src.domain.model.graph_store.graph_store import GraphStore
from src.infrastructure.graph.registry import (
    ENGINE_NEO4J,
    ENV_STORE_ID_PREFIX,
    GraphBackendFactory,
    GraphBackendRegistry,
    env_store_id,
    get_graph_backend_registry,
)


@pytest.mark.unit
class TestGraphBackendRegistry:
    def test_register_and_get_engine(self) -> None:
        reg = GraphBackendRegistry()
        store = Mock()
        reg.register_engine(ENGINE_NEO4J, store)
        assert reg.get_by_engine(ENGINE_NEO4J) is store

    def test_register_store_upsert_semantics(self) -> None:
        reg = GraphBackendRegistry()
        s1, s2 = Mock(), Mock()
        reg.register_store("store-1", s1)
        reg.register_store("store-1", s2)  # upsert
        assert reg.get_by_store_id("store-1") is s2

    def test_get_by_store_id_missing_returns_none(self) -> None:
        reg = GraphBackendRegistry()
        assert reg.get_by_store_id("nope") is None

    def test_unregister_store_idempotent(self) -> None:
        reg = GraphBackendRegistry()
        store = Mock()
        reg.register_store("store-1", store)
        assert reg.unregister_store("store-1") is store
        assert reg.unregister_store("store-1") is None  # idempotent

    def test_env_store_id_prefix(self) -> None:
        assert env_store_id(ENGINE_NEO4J).startswith(ENV_STORE_ID_PREFIX)
        reg = GraphBackendRegistry()
        assert reg.is_env_store_id(env_store_id("neo4j")) is True
        assert reg.is_env_store_id("db-store-1") is False

    def test_many_stores_same_engine(self) -> None:
        # WeKnora-style: multiple DB stores of the same engine type coexist.
        reg = GraphBackendRegistry()
        a, b = Mock(), Mock()
        reg.register_store("store-a", a)
        reg.register_store("store-b", b)
        assert reg.get_by_store_id("store-a") is a
        assert reg.get_by_store_id("store-b") is b

    def test_global_singleton(self) -> None:
        assert get_graph_backend_registry() is get_graph_backend_registry()


@pytest.mark.unit
class TestGraphBackendFactory:
    def test_dispatch_builds_registered_engine(self) -> None:
        factory = GraphBackendFactory()
        built = Mock()
        factory.register_builder(ENGINE_NEO4J, lambda store: built)
        store = GraphStore(id="s", tenant_id="t", name="n", engine_type=ENGINE_NEO4J)
        assert factory.build(store) is built

    def test_unknown_engine_raises(self) -> None:
        factory = GraphBackendFactory()
        store = GraphStore(id="s", tenant_id="t", name="n", engine_type="unknown")
        with pytest.raises(ValueError, match="Unsupported graph engine type"):
            factory.build(store)


@pytest.mark.unit
class TestGraphStoreMasking:
    def test_masked_connection_config_redacts_secrets(self) -> None:
        store = GraphStore(
            id="s",
            tenant_id="t",
            name="n",
            connection_config={
                "uri": "bolt://x",
                "user": "neo4j",
                "password": "secret",
                "api_key": "k",
                "token": "tok",
            },
        )
        masked = store.masked_connection_config()
        assert masked["uri"] == "bolt://x"
        assert masked["user"] == "neo4j"
        assert masked["password"] == "***"
        assert masked["api_key"] == "***"
        assert masked["token"] == "***"

    def test_masked_connection_config_empty_secrets_not_masked(self) -> None:
        store = GraphStore(
            id="s",
            tenant_id="t",
            name="n",
            connection_config={"password": ""},
        )
        assert store.masked_connection_config()["password"] == ""
