"""Unit tests for RetrievalStoreService."""

from __future__ import annotations

from unittest.mock import AsyncMock, Mock

import pytest

from src.application.services.retrieval_store_service import (
    RetrievalStoreInUse,
    RetrievalStoreNameConflict,
    RetrievalStoreNotFound,
    RetrievalStoreService,
    RetrievalStoreValidationError,
    _ssrf_guard,
    _validate_required_fields,
)
from src.domain.model.retrieval_store import RetrievalStore


def _make_store(**overrides) -> RetrievalStore:
    defaults = {
        "id": "store-1",
        "tenant_id": "tenant-1",
        "name": "prod-retrieval",
        "engine_type": "weknora_remote",
        "connection_config": {
            "base_url": "https://weknora.example.com/api/v1",
            "api_key": "secret",
            "knowledge_base_id": "kb-1",
        },
    }
    defaults.update(overrides)
    return RetrievalStore(**defaults)


def _mocks():
    repo = Mock()
    repo.save = AsyncMock(side_effect=lambda entity: entity)
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
class TestRetrievalStoreServiceCRUD:
    @pytest.mark.asyncio
    async def test_create_memstack_store_success(self) -> None:
        repo, registry, factory = _mocks()
        svc = RetrievalStoreService(repo, registry, factory)

        store = await svc.create_store(
            tenant_id="t",
            name="local",
            engine_type="memstack_pgvector",
        )

        assert store.name == "local"
        assert store.engine_type == "memstack_pgvector"
        repo.save.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_create_weknora_requires_kb_binding(self) -> None:
        repo, registry, factory = _mocks()
        svc = RetrievalStoreService(repo, registry, factory)

        with pytest.raises(RetrievalStoreValidationError, match="knowledge_base"):
            await svc.create_store(
                tenant_id="t",
                name="remote",
                engine_type="weknora_remote",
                connection_config={
                    "base_url": "https://weknora.example.com/api/v1",
                    "api_key": "secret",
                },
            )

    @pytest.mark.asyncio
    async def test_create_store_rejects_unknown_engine(self) -> None:
        repo, registry, factory = _mocks()
        svc = RetrievalStoreService(repo, registry, factory)

        with pytest.raises(RetrievalStoreValidationError, match="Unsupported engine type"):
            await svc.create_store(tenant_id="t", name="x", engine_type="unknown")

    @pytest.mark.asyncio
    async def test_create_store_rejects_duplicate_name(self) -> None:
        repo, registry, factory = _mocks()
        repo.find_by_name = AsyncMock(return_value=_make_store())
        svc = RetrievalStoreService(repo, registry, factory)

        with pytest.raises(RetrievalStoreNameConflict):
            await svc.create_store(
                tenant_id="t",
                name="prod-retrieval",
                engine_type="memstack_pgvector",
            )

    @pytest.mark.asyncio
    async def test_delete_store_rejects_when_projects_bound(self) -> None:
        repo, registry, factory = _mocks()
        repo.find_by_id = AsyncMock(return_value=_make_store())
        repo.count_projects_bound = AsyncMock(return_value=2)
        svc = RetrievalStoreService(repo, registry, factory)

        with pytest.raises(RetrievalStoreInUse, match="2 project"):
            await svc.delete_store("t", "store-1")

        repo.soft_delete.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_delete_store_succeeds_when_unbound(self) -> None:
        repo, registry, factory = _mocks()
        repo.find_by_id = AsyncMock(return_value=_make_store())
        svc = RetrievalStoreService(repo, registry, factory)

        await svc.delete_store("t", "store-1")

        repo.soft_delete.assert_awaited_once_with("t", "store-1")
        registry.unregister_store.assert_called_once_with("store-1")

    @pytest.mark.asyncio
    async def test_get_store_raises_when_absent(self) -> None:
        repo, registry, factory = _mocks()
        svc = RetrievalStoreService(repo, registry, factory)

        with pytest.raises(RetrievalStoreNotFound):
            await svc.get_store("t", "missing")

    @pytest.mark.asyncio
    async def test_resolve_store_view_masks_secrets(self) -> None:
        repo, registry, factory = _mocks()
        repo.find_by_id = AsyncMock(return_value=_make_store())
        svc = RetrievalStoreService(repo, registry, factory)

        view = await svc.resolve_store_view("t", "store-1")

        assert view.connection_config["api_key"] == "***"
        assert view.connection_config["base_url"] == "https://weknora.example.com/api/v1"


@pytest.mark.unit
class TestRetrievalStoreConnectionTest:
    @pytest.mark.asyncio
    async def test_test_connection_rejects_private_host(self) -> None:
        repo, registry, factory = _mocks()
        svc = RetrievalStoreService(repo, registry, factory)

        with pytest.raises(RetrievalStoreValidationError, match="non-public|Cannot resolve|host"):
            await svc.test_connection(
                engine_type="weknora_remote",
                connection_config={
                    "base_url": "http://10.0.0.1:8080/api/v1",
                    "api_key": "secret",
                    "knowledge_base_id": "kb-1",
                },
            )

    @pytest.mark.asyncio
    async def test_test_connection_uses_factory_backend(self) -> None:
        repo, registry, factory = _mocks()
        backend = Mock()
        backend.health_probe = AsyncMock(return_value=True)
        backend.detect_version = AsyncMock(return_value="1.2.3")
        backend.close = AsyncMock()
        factory.build = Mock(return_value=backend)
        svc = RetrievalStoreService(repo, registry, factory)

        version = await svc.test_connection(
            engine_type="memstack_pgvector",
            connection_config={},
        )

        assert version == "1.2.3"
        backend.health_probe.assert_awaited_once()
        backend.detect_version.assert_awaited_once()
        backend.close.assert_awaited_once()


@pytest.mark.unit
class TestRetrievalSSRFGuard:
    def test_rejects_loopback_in_production(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ENVIRONMENT", "production")
        monkeypatch.setenv("RETRIEVAL_STORE_PRIVATE_HOST_ALLOWLIST", "")

        with pytest.raises(RetrievalStoreValidationError):
            _ssrf_guard({"base_url": "http://127.0.0.1:8080"})

    def test_allows_loopback_in_local_development(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ENVIRONMENT", "development")
        monkeypatch.setenv("RETRIEVAL_STORE_PRIVATE_HOST_ALLOWLIST", "")

        _ssrf_guard({"base_url": "http://localhost:18080/api/v1"})
        _ssrf_guard({"base_url": "http://127.0.0.1:18080/api/v1"})

    def test_rejects_private_range(self) -> None:
        with pytest.raises(RetrievalStoreValidationError):
            _ssrf_guard({"base_url": "http://10.0.0.1:8080"})

    def test_allows_private_range_when_explicitly_allowlisted(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ENVIRONMENT", "production")
        monkeypatch.setenv("RETRIEVAL_STORE_PRIVATE_HOST_ALLOWLIST", "10.0.0.1")

        _ssrf_guard({"base_url": "http://10.0.0.1:8080"})

    def test_rejects_no_host(self) -> None:
        with pytest.raises(RetrievalStoreValidationError):
            _ssrf_guard({"base_url": "http://:8080"})

    def test_accepts_public_ip(self) -> None:
        _ssrf_guard({"base_url": "https://8.8.8.8"})


@pytest.mark.unit
class TestRetrievalRequiredFields:
    def test_weknora_requires_base_url_api_key_and_kb_scope(self) -> None:
        with pytest.raises(RetrievalStoreValidationError, match="base_url"):
            _validate_required_fields("weknora_remote", {})

        with pytest.raises(RetrievalStoreValidationError, match="knowledge_base"):
            _validate_required_fields(
                "weknora_remote",
                {"base_url": "https://weknora.example.com", "api_key": "secret"},
            )

    def test_weknora_ok_with_single_kb(self) -> None:
        _validate_required_fields(
            "weknora_remote",
            {
                "base_url": "https://weknora.example.com",
                "api_key": "secret",
                "knowledge_base_id": "kb-1",
            },
        )

    def test_memstack_pgvector_has_no_required_external_fields(self) -> None:
        _validate_required_fields("memstack_pgvector", {})
