"""Unit tests for GraphStoreService (CRUD, delete protection, SSRF, masking)."""

from __future__ import annotations

from unittest.mock import AsyncMock, Mock

import pytest

from src.application.services.graph_store_service import (
    GraphStoreInUse,
    GraphStoreNameConflict,
    GraphStoreNotFound,
    GraphStoreService,
    GraphStoreValidationError,
    _ssrf_guard,
    _validate_required_fields,
)
from src.domain.model.graph_store.graph_store import GraphStore


def _make_store(**overrides) -> GraphStore:
    defaults = {
        "id": "store-1",
        "tenant_id": "tenant-1",
        "name": "prod-graph",
        "engine_type": "neo4j",
        "connection_config": {"uri": "bolt://example.com:7687", "password": "s"},
    }
    defaults.update(overrides)
    return GraphStore(**defaults)


def _mocks():
    repo = Mock()
    repo.save = AsyncMock(side_effect=lambda e: e)
    repo.find_by_id = AsyncMock(return_value=None)
    repo.find_by_name = AsyncMock(return_value=None)
    repo.find_by_tenant = AsyncMock(return_value=[])
    repo.count_projects_bound = AsyncMock(return_value=0)
    repo.soft_delete = AsyncMock(return_value=True)
    registry = Mock()
    registry.unregister_store = Mock()
    factory = Mock()
    return repo, registry, factory


@pytest.mark.unit
class TestGraphStoreServiceCRUD:
    @pytest.mark.asyncio
    async def test_create_store_success(self) -> None:
        repo, registry, factory = _mocks()
        svc = GraphStoreService(repo, registry, factory)

        store = await svc.create_store(
            tenant_id="t",
            name="prod",
            engine_type="neo4j",
            connection_config={"uri": "bolt://example.com:7687"},
        )
        assert store.name == "prod"
        assert store.engine_type == "neo4j"
        repo.save.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_create_store_rejects_unknown_engine(self) -> None:
        repo, registry, factory = _mocks()
        svc = GraphStoreService(repo, registry, factory)
        with pytest.raises(GraphStoreValidationError, match="Unsupported engine type"):
            await svc.create_store(tenant_id="t", name="x", engine_type="mongodb")

    @pytest.mark.asyncio
    async def test_create_store_rejects_duplicate_name(self) -> None:
        repo, registry, factory = _mocks()
        repo.find_by_name = AsyncMock(return_value=_make_store())
        svc = GraphStoreService(repo, registry, factory)
        with pytest.raises(GraphStoreNameConflict):
            await svc.create_store(tenant_id="t", name="prod-graph", engine_type="neo4j")

    @pytest.mark.asyncio
    async def test_delete_store_rejects_when_projects_bound(self) -> None:
        repo, registry, factory = _mocks()
        repo.find_by_id = AsyncMock(return_value=_make_store())
        repo.count_projects_bound = AsyncMock(return_value=3)
        svc = GraphStoreService(repo, registry, factory)
        with pytest.raises(GraphStoreInUse, match="3 project"):
            await svc.delete_store("t", "store-1")
        repo.soft_delete.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_delete_store_succeeds_when_unbound(self) -> None:
        repo, registry, factory = _mocks()
        repo.find_by_id = AsyncMock(return_value=_make_store())
        svc = GraphStoreService(repo, registry, factory)
        await svc.delete_store("t", "store-1")
        repo.soft_delete.assert_awaited_once_with("t", "store-1")
        registry.unregister_store.assert_called_once_with("store-1")

    @pytest.mark.asyncio
    async def test_get_store_raises_when_absent(self) -> None:
        repo, registry, factory = _mocks()
        svc = GraphStoreService(repo, registry, factory)
        with pytest.raises(GraphStoreNotFound):
            await svc.get_store("t", "missing")

    @pytest.mark.asyncio
    async def test_resolve_store_view_masks_secrets(self) -> None:
        repo, registry, factory = _mocks()
        repo.find_by_id = AsyncMock(
            return_value=_make_store(connection_config={"uri": "u", "password": "secret"})
        )
        svc = GraphStoreService(repo, registry, factory)
        view = await svc.resolve_store_view("t", "store-1")
        assert view.connection_config["password"] == "***"
        assert view.connection_config["uri"] == "u"


@pytest.mark.unit
class TestGraphStoreServiceConnectionTest:
    @pytest.mark.asyncio
    async def test_test_connection_probes_and_closes_backend(self) -> None:
        repo, registry, factory = _mocks()
        backend = Mock()
        backend.health_probe = AsyncMock(return_value=True)
        backend.close = AsyncMock()
        backend.detected_version = "5.26"
        factory.build.return_value = backend
        svc = GraphStoreService(repo, registry, factory)

        version = await svc.test_connection(
            engine_type="neo4j",
            connection_config={"uri": "bolt://8.8.8.8:7687"},
        )

        assert version == "5.26"
        backend.health_probe.assert_awaited_once_with()
        backend.close.assert_awaited_once_with()

    @pytest.mark.asyncio
    async def test_test_connection_rejects_private_host(self) -> None:
        repo, registry, factory = _mocks()
        svc = GraphStoreService(repo, registry, factory)
        with pytest.raises(GraphStoreValidationError, match="non-public|Cannot resolve|host"):
            await svc.test_connection(
                engine_type="neo4j",
                connection_config={"uri": "bolt://127.0.0.1:7687"},
            )

    @pytest.mark.asyncio
    async def test_test_connection_rejects_missing_required_field(self) -> None:
        repo, registry, factory = _mocks()
        svc = GraphStoreService(repo, registry, factory)
        with pytest.raises(GraphStoreValidationError, match="Missing required"):
            await svc.test_connection(engine_type="neo4j", connection_config={})


@pytest.mark.unit
class TestSSRFGuard:
    def test_rejects_loopback(self) -> None:
        with pytest.raises(GraphStoreValidationError):
            _ssrf_guard({"uri": "bolt://127.0.0.1:7687"})

    def test_rejects_private_range(self) -> None:
        with pytest.raises(GraphStoreValidationError):
            _ssrf_guard({"uri": "bolt://10.0.0.1:7687"})

    def test_rejects_no_host(self) -> None:
        with pytest.raises(GraphStoreValidationError):
            _ssrf_guard({"uri": "bolt://:7687"})

    def test_accepts_public_ip(self) -> None:
        # 8.8.8.8 is a public address; should not raise.
        _ssrf_guard({"uri": "bolt://8.8.8.8:7687"})


@pytest.mark.unit
class TestRequiredFields:
    def test_neo4j_requires_uri(self) -> None:
        with pytest.raises(GraphStoreValidationError, match="uri"):
            _validate_required_fields("neo4j", {})

    def test_neo4j_ok_with_uri(self) -> None:
        _validate_required_fields("neo4j", {"uri": "bolt://x"})
