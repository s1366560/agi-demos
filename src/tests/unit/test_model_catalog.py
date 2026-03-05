"""Unit tests for the model catalog system (P1-T9).

Covers:
- ModelCatalogService: loading, lookup, search, list, variants, refresh
- model_registry backward compatibility: all 6 public functions
- CategoryRouter.select_model_from_catalog
- ModelMetadata new catalog fields
"""

import json
from pathlib import Path

import pytest

from src.domain.llm_providers.models import (
    DEFAULT_MODEL_METADATA,
    ModelMetadata,
)
from src.domain.llm_providers.repositories import ModelCatalogPort
from src.infrastructure.llm.model_catalog import ModelCatalogService
from src.infrastructure.llm.model_registry import (
    ModelLimits,
    clamp_max_tokens,
    get_model_chars_per_token,
    get_model_context_window,
    get_model_input_budget,
    get_model_limits,
    get_model_max_input_tokens,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_TEST_SNAPSHOT = {
    "_meta": {"version": "1.0.0"},
    "models": {
        "test-model-alpha": {
            "name": "test-model-alpha",
            "context_length": 64000,
            "max_output_tokens": 4096,
            "capabilities": ["chat", "function_calling"],
            "supports_streaming": True,
            "supports_json_mode": True,
            "provider": "acme",
            "modalities": ["text"],
            "family": "alpha",
            "description": "Alpha model for testing",
        },
        "test-model-alpha-v2": {
            "name": "test-model-alpha-v2",
            "context_length": 128000,
            "max_output_tokens": 8192,
            "capabilities": ["chat"],
            "supports_streaming": True,
            "supports_json_mode": False,
            "provider": "acme",
            "modalities": ["text"],
            "family": "alpha",
            "description": "Alpha v2 model for testing",
        },
        "test-model-beta": {
            "name": "test-model-beta",
            "context_length": 32000,
            "max_output_tokens": 2048,
            "capabilities": ["chat"],
            "supports_streaming": True,
            "supports_json_mode": False,
            "provider": "betacorp",
            "modalities": ["text", "image"],
            "family": "beta",
            "description": "Beta model from betacorp",
            "is_deprecated": True,
        },
        "test-model-gamma": {
            "name": "test-model-gamma",
            "context_length": 100000,
            "max_output_tokens": 4096,
            "capabilities": ["chat", "code"],
            "supports_streaming": True,
            "supports_json_mode": True,
            "provider": "acme",
            "modalities": ["text"],
            "family": "gamma",
            "description": "Gamma model for coding",
            "max_input_tokens": 90000,
            "input_budget_ratio": 0.85,
            "chars_per_token": 1.5,
        },
    },
}


@pytest.fixture()
def snapshot_path(tmp_path: Path) -> Path:
    """Write a test snapshot JSON and return its path."""
    p = tmp_path / "test_snapshot.json"
    p.write_text(json.dumps(_TEST_SNAPSHOT), encoding="utf-8")
    return p


@pytest.fixture()
def catalog(snapshot_path: Path) -> ModelCatalogService:
    """Return a catalog service backed by the test snapshot."""
    return ModelCatalogService(snapshot_path=snapshot_path)


@pytest.fixture()
def empty_catalog(tmp_path: Path) -> ModelCatalogService:
    """Return a catalog with no snapshot file (domain defaults only)."""
    missing = tmp_path / "does_not_exist.json"
    return ModelCatalogService(snapshot_path=missing)


# ===========================================================================
# ModelCatalogService tests
# ===========================================================================


@pytest.mark.unit
class TestModelCatalogService:
    """Tests for ModelCatalogService."""

    def test_implements_port(self, catalog: ModelCatalogService) -> None:
        """Catalog service must implement ModelCatalogPort."""
        assert isinstance(catalog, ModelCatalogPort)

    # -- Loading --

    def test_load_merges_domain_and_snapshot(self, catalog: ModelCatalogService) -> None:
        """Snapshot models overlay domain defaults."""
        # Snapshot-only model
        assert catalog.get_model("test-model-alpha") is not None
        # Domain-default model still present
        assert catalog.get_model("gpt-4-turbo") is not None

    def test_model_count_includes_both_sources(self, catalog: ModelCatalogService) -> None:
        """model_count reflects merged catalog size."""
        domain_count = len(DEFAULT_MODEL_METADATA)
        snapshot_count = len(_TEST_SNAPSHOT["models"])
        # Some models might overlap; count should be at least max of both
        assert catalog.model_count >= max(domain_count, snapshot_count)

    def test_snapshot_overrides_domain_default(self, snapshot_path: Path) -> None:
        """When a model exists in both domain and snapshot, snapshot wins."""
        # Create a snapshot that overrides a domain model
        override_snapshot = {
            "_meta": {"version": "1.0.0"},
            "models": {
                "gpt-4-turbo": {
                    "name": "gpt-4-turbo",
                    "context_length": 999999,
                    "max_output_tokens": 1234,
                    "capabilities": ["chat"],
                    "supports_streaming": True,
                    "supports_json_mode": False,
                    "provider": "test-override",
                    "modalities": ["text"],
                },
            },
        }
        p = snapshot_path.parent / "override.json"
        p.write_text(json.dumps(override_snapshot), encoding="utf-8")
        svc = ModelCatalogService(snapshot_path=p)
        meta = svc.get_model("gpt-4-turbo")
        assert meta is not None
        assert meta.context_length == 999999
        assert meta.provider == "test-override"

    def test_missing_snapshot_uses_domain_only(self, empty_catalog: ModelCatalogService) -> None:
        """When snapshot file is missing, only domain defaults load."""
        assert empty_catalog.get_model("gpt-4-turbo") is not None
        assert empty_catalog.get_model("test-model-alpha") is None
        assert empty_catalog.model_count == len(DEFAULT_MODEL_METADATA)

    # -- get_model --

    def test_get_model_exact_match(self, catalog: ModelCatalogService) -> None:
        """get_model returns metadata for an exact name match."""
        meta = catalog.get_model("test-model-alpha")
        assert meta is not None
        assert meta.name == "test-model-alpha"
        assert meta.context_length == 64000
        assert meta.provider == "acme"

    def test_get_model_not_found(self, catalog: ModelCatalogService) -> None:
        """get_model returns None for unknown models."""
        assert catalog.get_model("nonexistent-model-xyz") is None

    # -- search_models --

    def test_search_by_name(self, catalog: ModelCatalogService) -> None:
        """Search matches on model name substring."""
        results = catalog.search_models("alpha")
        names = [m.name for m in results]
        assert "test-model-alpha" in names
        assert "test-model-alpha-v2" in names

    def test_search_by_family(self, catalog: ModelCatalogService) -> None:
        """Search matches on family field."""
        results = catalog.search_models("gamma")
        assert any(m.name == "test-model-gamma" for m in results)

    def test_search_by_provider(self, catalog: ModelCatalogService) -> None:
        """Search matches on provider field."""
        results = catalog.search_models("betacorp")
        assert any(m.name == "test-model-beta" for m in results)

    def test_search_by_description(self, catalog: ModelCatalogService) -> None:
        """Search matches on description substring."""
        results = catalog.search_models("coding")
        assert any(m.name == "test-model-gamma" for m in results)

    def test_search_with_provider_filter(self, catalog: ModelCatalogService) -> None:
        """Provider filter restricts search results."""
        results = catalog.search_models("model", provider="betacorp")
        assert all(m.provider == "betacorp" for m in results)
        assert len(results) >= 1

    def test_search_limit(self, catalog: ModelCatalogService) -> None:
        """Limit caps result count."""
        results = catalog.search_models("model", limit=1)
        assert len(results) <= 1

    def test_search_no_results(self, catalog: ModelCatalogService) -> None:
        """Search with unmatched query returns empty list."""
        results = catalog.search_models("zzzznonexistent")
        assert results == []

    # -- list_models --

    def test_list_models_excludes_deprecated(self, catalog: ModelCatalogService) -> None:
        """Default list_models excludes deprecated models."""
        results = catalog.list_models()
        names = [m.name for m in results]
        assert "test-model-beta" not in names

    def test_list_models_include_deprecated(self, catalog: ModelCatalogService) -> None:
        """include_deprecated=True shows deprecated models."""
        results = catalog.list_models(include_deprecated=True)
        names = [m.name for m in results]
        assert "test-model-beta" in names

    def test_list_models_provider_filter(self, catalog: ModelCatalogService) -> None:
        """Provider filter limits listed models."""
        results = catalog.list_models(provider="acme")
        assert all(m.provider == "acme" for m in results)
        assert len(results) >= 2

    # -- get_variants --

    def test_get_variants_finds_variants(self, catalog: ModelCatalogService) -> None:
        """get_variants returns models with base prefix."""
        variants = catalog.get_variants("test-model-alpha")
        names = [v.name for v in variants]
        assert "test-model-alpha-v2" in names
        # Base model itself is excluded
        assert "test-model-alpha" not in names

    def test_get_variants_no_variants(self, catalog: ModelCatalogService) -> None:
        """get_variants returns empty when no variants exist."""
        variants = catalog.get_variants("test-model-gamma")
        assert variants == []

    # -- refresh --

    def test_refresh_reloads(self, catalog: ModelCatalogService) -> None:
        """refresh() clears and reloads the catalog."""
        count_before = catalog.model_count
        catalog.refresh()
        assert catalog.model_count == count_before

    # -- model_count --

    def test_model_count_positive(self, catalog: ModelCatalogService) -> None:
        """model_count returns a positive integer."""
        assert catalog.model_count > 0


# ===========================================================================
# ModelMetadata new fields tests
# ===========================================================================


@pytest.mark.unit
class TestModelMetadataNewFields:
    """Tests for new ModelMetadata catalog fields added in P1-T1."""

    def test_default_values(self) -> None:
        """New optional fields default correctly."""
        meta = ModelMetadata(name="minimal")
        assert meta.provider is None
        assert meta.modalities == []
        assert meta.variants == []
        assert meta.default_variant is None
        assert meta.family is None
        assert meta.release_date is None
        assert meta.is_deprecated is False
        assert meta.description is None
        assert meta.max_input_tokens is None
        assert meta.input_budget_ratio == 0.9
        assert meta.chars_per_token == 3.0

    def test_domain_defaults_have_provider(self) -> None:
        """All DEFAULT_MODEL_METADATA entries have a provider set."""
        for name, meta in DEFAULT_MODEL_METADATA.items():
            assert meta.provider is not None, f"{name} missing provider"

    def test_domain_defaults_have_family(self) -> None:
        """All DEFAULT_MODEL_METADATA entries have a family set."""
        for name, meta in DEFAULT_MODEL_METADATA.items():
            assert meta.family is not None, f"{name} missing family"

    def test_domain_defaults_have_description(self) -> None:
        """All DEFAULT_MODEL_METADATA entries have a description."""
        for name, meta in DEFAULT_MODEL_METADATA.items():
            assert meta.description is not None, f"{name} missing description"

    def test_snapshot_entries_have_catalog_fields(self, catalog: ModelCatalogService) -> None:
        """Snapshot models should have provider, family, description."""
        meta = catalog.get_model("test-model-alpha")
        assert meta is not None
        assert meta.provider == "acme"
        assert meta.family == "alpha"
        assert meta.description is not None


# ===========================================================================
# model_registry backward compatibility tests
# ===========================================================================


@pytest.mark.unit
class TestModelRegistryBackwardCompat:
    """Verify all 6 public functions in model_registry still work."""

    # -- get_model_limits --

    def test_get_model_limits_known_model(self) -> None:
        """get_model_limits returns correct data for a known model."""
        limits = get_model_limits("qwen-max")
        assert isinstance(limits, ModelLimits)
        assert limits.max_output_tokens == 8192
        assert limits.context_window == 32768
        assert limits.max_input_tokens == 30720

    def test_get_model_limits_with_provider_prefix(self) -> None:
        """Provider prefix is stripped correctly."""
        limits = get_model_limits("dashscope/qwen-max")
        assert limits.max_output_tokens == 8192

    def test_get_model_limits_overrides(self) -> None:
        """provider_config_overrides take precedence."""
        limits = get_model_limits(
            "qwen-max",
            provider_config_overrides={
                "max_output_tokens": 999,
                "context_window": 10000,
            },
        )
        assert limits.max_output_tokens == 999
        assert limits.context_window == 10000

    def test_get_model_limits_unknown_model(self) -> None:
        """Unknown models get default context window."""
        limits = get_model_limits("totally-unknown-model-xyz")
        assert limits.context_window == 128_000
        assert limits.max_output_tokens is None

    # -- clamp_max_tokens --

    def test_clamp_max_tokens_within_limit(self) -> None:
        """Value under limit is returned as-is."""
        result = clamp_max_tokens("qwen-max", 4096)
        assert result == 4096

    def test_clamp_max_tokens_exceeds_limit(self) -> None:
        """Value above limit is clamped."""
        result = clamp_max_tokens("qwen-max", 99999)
        assert result == 8192

    def test_clamp_max_tokens_unknown_model(self) -> None:
        """Unknown model: value returned unchanged."""
        result = clamp_max_tokens("unknown-model-xyz", 12345)
        assert result == 12345

    # -- get_model_context_window --

    def test_context_window_known_model(self) -> None:
        """Known model returns its context window."""
        ctx = get_model_context_window("deepseek-chat")
        assert ctx == 65536

    def test_context_window_unknown_model(self) -> None:
        """Unknown model returns default 128000."""
        ctx = get_model_context_window("unknown-model-xyz")
        assert ctx == 128_000

    def test_context_window_with_prefix(self) -> None:
        """Provider prefix is stripped."""
        ctx = get_model_context_window("deepseek/deepseek-chat")
        assert ctx == 65536

    # -- get_model_max_input_tokens --

    def test_max_input_tokens_explicit_limit(self) -> None:
        """Model with explicit input cap returns it."""
        result = get_model_max_input_tokens("qwen-max")
        assert result == 30720

    def test_max_input_tokens_derived(self) -> None:
        """Model without explicit cap derives from context - output."""
        result = get_model_max_input_tokens("deepseek-chat", max_output_tokens=8192)
        # context_window(65536) - 8192 = 57344
        assert result == 57344

    def test_max_input_tokens_positive(self) -> None:
        """Result is always >= 1."""
        result = get_model_max_input_tokens("unknown-model-xyz")
        assert result >= 1

    # -- get_model_input_budget --

    def test_input_budget_known_ratio(self) -> None:
        """Model with known ratio applies it."""
        budget = get_model_input_budget("qwen-max")
        # 30720 * 0.85 = 26112
        assert budget == 26112

    def test_input_budget_default_ratio(self) -> None:
        """Model without known ratio uses default 0.9."""
        budget = get_model_input_budget("deepseek-chat")
        max_input = get_model_max_input_tokens("deepseek-chat")
        expected = max(1, int(max_input * 0.9))
        assert budget == expected

    # -- get_model_chars_per_token --

    def test_chars_per_token_known(self) -> None:
        """Model with known chars/token returns it."""
        cpt = get_model_chars_per_token("qwen-max")
        assert cpt == 1.2

    def test_chars_per_token_default(self) -> None:
        """Unknown model returns default 3.0."""
        cpt = get_model_chars_per_token("unknown-model-xyz")
        assert cpt == 3.0


# ===========================================================================
# CategoryRouter.select_model_from_catalog tests
# ===========================================================================


@pytest.mark.unit
class TestCategoryRouterCatalogSelection:
    """Tests for CategoryRouter.select_model_from_catalog."""

    def test_returns_model_name(self) -> None:
        """select_model_from_catalog returns a model in the pool."""
        from src.infrastructure.llm.category_router import (
            CategoryRouter,
            TaskCategory,
        )

        router = CategoryRouter(
            provider_configs={
                "dashscope": ["qwen-max", "qwen-plus"],
                "deepseek": ["deepseek-chat"],
            }
        )
        result = router.select_model_from_catalog(TaskCategory.CODE)
        # Should return one of the available models (or None)
        if result is not None:
            assert result in {"qwen-max", "qwen-plus", "deepseek-chat"}

    def test_skips_deprecated_models(self) -> None:
        """Deprecated models in catalog are skipped."""
        from src.infrastructure.llm.category_router import (
            CategoryRouter,
            TaskCategory,
        )

        router = CategoryRouter(
            provider_configs={
                # gpt-4 is deprecated in the snapshot
                "openai": ["gpt-4"],
            }
        )
        result = router.select_model_from_catalog(TaskCategory.DEFAULT)
        # gpt-4 is marked deprecated in snapshot; should not be returned
        # unless it's the only non-deprecated option
        assert result is None or result != "gpt-4"

    def test_returns_none_with_no_providers(self) -> None:
        """Empty provider config yields None."""
        from src.infrastructure.llm.category_router import (
            CategoryRouter,
            TaskCategory,
        )

        router = CategoryRouter(provider_configs={})
        result = router.select_model_from_catalog(TaskCategory.DEFAULT)
        assert result is None

    def test_available_providers_filter(self) -> None:
        """available_providers restricts model selection."""
        from src.infrastructure.llm.category_router import (
            CategoryRouter,
            TaskCategory,
        )

        router = CategoryRouter(
            provider_configs={
                "dashscope": ["qwen-max"],
                "deepseek": ["deepseek-chat"],
            }
        )
        result = router.select_model_from_catalog(
            TaskCategory.CODE, available_providers=["deepseek"]
        )
        if result is not None:
            assert result == "deepseek-chat"


# ===========================================================================
# ModelCatalogPort ABC tests
# ===========================================================================


@pytest.mark.unit
class TestModelCatalogPortABC:
    """Verify ModelCatalogPort is a proper ABC."""

    def test_cannot_instantiate_directly(self) -> None:
        """Cannot instantiate the abstract base class."""
        with pytest.raises(TypeError):
            ModelCatalogPort()  # type: ignore[abstract]
