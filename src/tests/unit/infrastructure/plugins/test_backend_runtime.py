"""Unit tests for the R3 backend capability resolution seam (R3a)."""

from __future__ import annotations

from typing import Any

import pytest

from src.domain.model.plugins import CapabilityKind, PluginManifest, parse_plugin_manifest
from src.domain.ports.plugins.contracts import (
    EmbeddingResult,
    RerankResult,
)
from src.infrastructure.plugins.backend_adapters import (
    PluginEmbedderAdapter,
    PluginRerankerAdapter,
)
from src.infrastructure.plugins.backend_runtime import (
    BackendResolutionError,
    resolve_backend,
)
from src.infrastructure.plugins.context import CapabilityRegistry


def _signed_manifest(capability_kind: str, capability_id: str = "default") -> PluginManifest:
    return parse_plugin_manifest(
        {
            "schemaVersion": 1,
            "id": f"test-{capability_kind}",
            "version": "1.0.0",
            "runtime": "python-trusted",
            "trust": "signed",
            "provides": [{"kind": capability_kind, "id": capability_id}],
            "activation": {"defaultScope": "tenant"},
        }
    )


class _FakeEmbedder:
    def __init__(self) -> None:
        self.calls: list[tuple[str, list[str]]] = []

    async def embed(self, route: Any, inputs: Any) -> EmbeddingResult:
        self.calls.append((route.model_id, list(inputs)))
        vectors = tuple(tuple(float(len(text)) for _ in range(2)) for text in inputs)
        return EmbeddingResult(vectors=vectors, dimension=2, model_id=route.model_id)


class _FakeReranker:
    def __init__(self) -> None:
        self.calls: list[tuple[str, list[str]]] = []

    async def rerank(self, route: Any, query: str, passages: Any) -> RerankResult:
        self.calls.append((query, list(passages)))
        scores = tuple(float(len(passage)) for passage in passages)
        return RerankResult(scores=scores, model_id=route.model_id)


@pytest.mark.unit
class TestResolveBackend:
    def test_plugin_row_wins_over_builtin(self) -> None:
        registry = CapabilityRegistry()
        plugin_impl = _FakeEmbedder()
        registry.register(
            _signed_manifest("embedder"), CapabilityKind.EMBEDDER, "default", plugin_impl
        )
        builtin_impl = _FakeEmbedder()

        selection = resolve_backend(registry, CapabilityKind.EMBEDDER, builtin=builtin_impl)

        assert selection.scope == "plugin"
        assert selection.implementation is plugin_impl
        assert selection.plugin_id == "test-embedder"

    def test_builtin_fallback_when_registry_empty(self) -> None:
        builtin_impl = _FakeEmbedder()
        selection = resolve_backend(
            CapabilityRegistry(), CapabilityKind.EMBEDDER, builtin=builtin_impl
        )
        assert selection.scope == "builtin"
        assert selection.implementation is builtin_impl
        assert selection.plugin_id == "memstack-kernel"

    def test_builtin_fallback_when_registry_absent(self) -> None:
        builtin_impl = _FakeEmbedder()
        selection = resolve_backend(None, CapabilityKind.EMBEDDER, builtin=builtin_impl)
        assert selection.scope == "builtin"

    def test_missing_row_and_builtin_raises(self) -> None:
        with pytest.raises(BackendResolutionError):
            resolve_backend(CapabilityRegistry(), CapabilityKind.EMBEDDER)

    def test_non_backend_kind_rejected(self) -> None:
        with pytest.raises(BackendResolutionError, match="not a backend"):
            resolve_backend(CapabilityRegistry(), CapabilityKind.TOOL, builtin=object())

    def test_validator_runs_for_plugin_and_builtin(self) -> None:
        seen: list[str] = []

        def validator(impl: object) -> None:
            seen.append(type(impl).__name__)

        registry = CapabilityRegistry()
        registry.register(
            _signed_manifest("reranker"), CapabilityKind.RERANKER, "default", _FakeReranker()
        )
        resolve_backend(registry, CapabilityKind.RERANKER, validator=validator)
        assert seen == ["_FakeReranker"]

        resolve_backend(
            CapabilityRegistry(),
            CapabilityKind.RERANKER,
            builtin=_FakeReranker(),
            validator=validator,
        )
        assert seen == ["_FakeReranker", "_FakeReranker"]


@pytest.mark.unit
class TestPluginEmbedderAdapter:
    async def test_create_single_text(self) -> None:
        from src.infrastructure.plugins.backend_adapters import route_from_provider_config

        impl = _FakeEmbedder()
        route = _make_route(route_from_provider_config)
        adapter = PluginEmbedderAdapter(impl, route, embedding_dim=2)

        vector = await adapter.create("hello")

        assert vector == [5.0, 5.0]
        assert impl.calls == [("test-embedding", ["hello"])]
        assert adapter.embedding_dim == 2

    async def test_create_list_and_batch(self) -> None:
        from src.infrastructure.plugins.backend_adapters import route_from_provider_config

        impl = _FakeEmbedder()
        route = _make_route(route_from_provider_config)
        adapter = PluginEmbedderAdapter(impl, route)

        vectors = await adapter.create(["aa", "b"])
        assert vectors == [[2.0, 2.0], [1.0, 1.0]]

        batch = await adapter.create_batch(["xyz"])
        assert batch == [[3.0, 3.0]]


@pytest.mark.unit
class TestPluginRerankerAdapter:
    async def test_rank_sorts_descending_and_applies_top_n(self) -> None:
        from src.infrastructure.plugins.backend_adapters import route_from_provider_config

        impl = _FakeReranker()
        route = _make_route(route_from_provider_config)
        adapter = PluginRerankerAdapter(impl, route)

        ranked = await adapter.rank("q", ["a", "bbbb", "cc"], top_n=2)

        assert ranked == [("bbbb", 4.0), ("cc", 2.0)]
        assert impl.calls == [("q", ["a", "bbbb", "cc"])]

    async def test_rank_rejects_score_count_mismatch(self) -> None:
        from src.infrastructure.plugins.backend_adapters import route_from_provider_config

        class _BadReranker:
            async def rerank(self, route: Any, query: str, passages: Any) -> RerankResult:
                return RerankResult(scores=(1.0,), model_id="m")

        adapter = PluginRerankerAdapter(_BadReranker(), _make_route(route_from_provider_config))
        with pytest.raises(ValueError, match="scores"):
            await adapter.rank("q", ["a", "b"])


def _make_route(route_factory: Any) -> Any:
    from datetime import UTC, datetime
    from uuid import uuid4

    from src.domain.llm_providers.models import ProviderConfig, ProviderType

    now = datetime.now(UTC)
    provider_config = ProviderConfig(
        id=uuid4(),
        name="Test Provider",
        provider_type=ProviderType.OPENAI,
        llm_model="test-model",
        embedding_model="test-embedding",
        reranker_model="test-reranker",
        api_key_encrypted="encrypted_test-key",
        created_at=now,
        updated_at=now,
    )
    return route_factory(provider_config, model_id="test-embedding")


def _make_provider_config() -> Any:
    from datetime import UTC, datetime
    from uuid import uuid4

    from src.domain.llm_providers.models import ProviderConfig, ProviderType

    now = datetime.now(UTC)
    return ProviderConfig(
        id=uuid4(),
        name="Test Provider",
        provider_type=ProviderType.OPENAI,
        llm_model="test-model",
        embedding_model="test-embedding",
        reranker_model="test-reranker",
        api_key_encrypted="encrypted_test-key",
        created_at=now,
        updated_at=now,
    )


@pytest.fixture
def isolated_runtime_host() -> Any:
    """Install an isolated plugin runtime host for the test."""
    from src.infrastructure.plugins.runtime_host import (
        PlatformPluginRuntimeHost,
        reset_platform_plugin_runtime_host,
        set_platform_plugin_runtime_host,
    )

    registry = CapabilityRegistry()
    set_platform_plugin_runtime_host(PlatformPluginRuntimeHost(capability_registry=registry))
    yield registry
    reset_platform_plugin_runtime_host()


@pytest.mark.unit
class TestProviderFactorySeam:
    def test_embedder_falls_back_to_builtin_when_registry_empty(
        self, isolated_runtime_host: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from src.infrastructure.llm import provider_factory
        from src.infrastructure.llm.litellm import litellm_embedder

        sentinel = object()
        monkeypatch.setattr(litellm_embedder, "LiteLLMEmbedder", lambda **kwargs: sentinel)

        result = provider_factory.AIServiceFactory.create_embedder(_make_provider_config())

        assert result is sentinel

    def test_embedder_plugin_row_wins(self, isolated_runtime_host: Any) -> None:
        from src.infrastructure.llm import provider_factory

        isolated_runtime_host.register(
            _signed_manifest("embedder"), CapabilityKind.EMBEDDER, "default", _FakeEmbedder()
        )

        result = provider_factory.AIServiceFactory.create_embedder(_make_provider_config())

        assert isinstance(result, PluginEmbedderAdapter)

    def test_embedder_plugin_row_must_satisfy_contract(self, isolated_runtime_host: Any) -> None:
        from src.infrastructure.llm import provider_factory

        isolated_runtime_host.register(
            _signed_manifest("embedder"), CapabilityKind.EMBEDDER, "default", object()
        )

        with pytest.raises(TypeError, match="EmbedderCapability"):
            provider_factory.AIServiceFactory.create_embedder(_make_provider_config())

    def test_reranker_plugin_row_wins(self, isolated_runtime_host: Any) -> None:
        from src.infrastructure.llm import provider_factory

        isolated_runtime_host.register(
            _signed_manifest("reranker"),
            CapabilityKind.RERANKER,
            "default",
            _FakeReranker(),
        )

        result = provider_factory.AIServiceFactory.create_reranker(_make_provider_config())

        assert isinstance(result, PluginRerankerAdapter)

    def test_reranker_falls_back_to_builtin_when_registry_empty(
        self, isolated_runtime_host: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from src.infrastructure.llm import provider_factory
        from src.infrastructure.llm.litellm import litellm_reranker

        sentinel = object()
        monkeypatch.setattr(litellm_reranker, "LiteLLMReranker", lambda config: sentinel)

        result = provider_factory.AIServiceFactory.create_reranker(_make_provider_config())

        assert result is sentinel


@pytest.mark.unit
class TestTrustGateExcludesUntrustedBackends:
    @pytest.mark.parametrize(
        "kind",
        [
            "embedder",
            "reranker",
            "graph_backend",
            "retrieval_backend",
            "workflow_engine",
            "telemetry_exporter",
        ],
    )
    def test_untrusted_plugin_cannot_provide_backend_kind(self, kind: str) -> None:
        from src.infrastructure.plugins.governance import PluginTrustGate

        manifest = parse_plugin_manifest(
            {
                "schemaVersion": 1,
                "id": f"untrusted-{kind}",
                "version": "1.0.0",
                "runtime": "wasm",
                "trust": "untrusted",
                "provides": [{"kind": kind, "id": "default"}],
                "activation": {"defaultScope": "tenant"},
            }
        )

        decision = PluginTrustGate().decide(manifest, frozenset())

        assert decision.allowed is False
        assert "tool" in decision.reason


@pytest.mark.unit
class TestBuiltinManifestRows:
    def test_memory_backends_manifest_declares_embedder_and_reranker(self) -> None:
        from src.infrastructure.plugins.builtin_manifests import (
            default_builtin_manifests,
        )

        manifests = default_builtin_manifests()
        assert "memory-backends" in manifests
        kinds = {(cap.kind, cap.id) for cap in manifests["memory-backends"].provides}
        assert (CapabilityKind.EMBEDDER, "default") in kinds
        assert (CapabilityKind.RERANKER, "default") in kinds


@pytest.mark.unit
class TestHybridSearchRerankerSeam:
    def _make_search(self, reranker: Any = None) -> Any:
        from unittest.mock import MagicMock

        from src.infrastructure.graph.schemas import SearchResultItem  # noqa: F401
        from src.infrastructure.graph.search.hybrid_search import HybridSearch

        return HybridSearch(
            neo4j_client=MagicMock(),
            embedding_service=MagicMock(),
            reranker=reranker,
        )

    def _items(self) -> list[Any]:
        from src.infrastructure.graph.schemas import SearchResultItem

        return [
            SearchResultItem(type="entity", uuid="1", content="aa", score=0.9),
            SearchResultItem(type="entity", uuid="2", content="bbbb", score=0.5),
            SearchResultItem(type="entity", uuid="3", content="c", score=0.1),
        ]

    async def test_no_reranker_keeps_builtin_order(self) -> None:
        search = self._make_search()
        items = self._items()

        result = await search._apply_reranker("q", items)

        assert result is items

    async def test_plugin_reranker_reorders_by_score(self) -> None:
        class _Reranker:
            async def rank(
                self, query: str, passages: list[str], top_n: int | None = None
            ) -> list[tuple[str, float]]:
                return sorted(
                    ((p, float(len(p))) for p in passages),
                    key=lambda item: item[1],
                    reverse=True,
                )

        search = self._make_search(reranker=_Reranker())
        result = await search._apply_reranker("q", self._items())

        assert [item.uuid for item in result] == ["2", "1", "3"]
        assert result[0].score == 4.0

    async def test_reranker_failure_falls_back_to_builtin_order(self) -> None:
        class _FailingReranker:
            async def rank(
                self, query: str, passages: list[str], top_n: int | None = None
            ) -> list[tuple[str, float]]:
                raise RuntimeError("provider down")

        search = self._make_search(reranker=_FailingReranker())
        items = self._items()
        result = await search._apply_reranker("q", items)

        assert [item.uuid for item in result] == ["1", "2", "3"]
        assert result[0].score == 0.9
