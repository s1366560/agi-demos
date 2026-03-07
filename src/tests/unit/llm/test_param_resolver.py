"""Tests for ``src.infrastructure.llm.param_resolver``."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

from src.domain.llm_providers.models import ModelMetadata
from src.infrastructure.llm.param_resolver import resolve_llm_params

# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _make_metadata(**overrides: Any) -> ModelMetadata:
    """Create a ``ModelMetadata`` with sensible defaults, selectively overridden."""
    defaults: dict[str, Any] = {
        "name": "test-model",
        "context_length": 128000,
        "max_output_tokens": 4096,
        # support flags
        "supports_temperature": True,
        "supports_top_p": True,
        "supports_frequency_penalty": True,
        "supports_presence_penalty": True,
        "supports_seed": True,
        "supports_stop": True,
        "supports_response_format": True,
        # defaults
        "default_temperature": 0.7,
        "default_top_p": 1.0,
        "default_frequency_penalty": 0.0,
        "default_presence_penalty": 0.0,
        # ranges
        "temperature_range": [0.0, 2.0],
        "top_p_range": [0.0, 1.0],
    }
    defaults.update(overrides)
    return ModelMetadata(**defaults)


def _mock_catalog(
    meta: ModelMetadata | None = None,
) -> MagicMock:
    """Return a mock ``ModelCatalogService`` that returns *meta*."""
    catalog = MagicMock(spec=["get_model_fuzzy"])
    catalog.get_model_fuzzy.return_value = meta
    return catalog


# ------------------------------------------------------------------
# Resolution chain priority tests
# ------------------------------------------------------------------


class TestResolutionChain:
    """User overrides > provider config > model defaults > omit."""

    def test_user_override_wins_over_provider_config(self) -> None:
        meta = _make_metadata(default_temperature=0.7)
        catalog = _mock_catalog(meta)
        result = resolve_llm_params(
            "test-model",
            user_overrides={"temperature": 0.1},
            provider_config={"temperature": 0.5},
            catalog=catalog,
        )
        assert result["temperature"] == 0.1

    def test_provider_config_wins_over_model_default(self) -> None:
        meta = _make_metadata(default_temperature=0.7)
        catalog = _mock_catalog(meta)
        result = resolve_llm_params(
            "test-model",
            provider_config={"temperature": 0.5},
            catalog=catalog,
        )
        assert result["temperature"] == 0.5

    def test_model_default_used_when_no_overrides(self) -> None:
        meta = _make_metadata(default_temperature=0.7)
        catalog = _mock_catalog(meta)
        result = resolve_llm_params("test-model", catalog=catalog)
        assert result["temperature"] == 0.7

    def test_param_omitted_when_no_source(self) -> None:
        meta = _make_metadata(default_temperature=None)
        catalog = _mock_catalog(meta)
        result = resolve_llm_params("test-model", catalog=catalog)
        assert "temperature" not in result

    def test_all_none_inputs_produces_only_drop_params(self) -> None:
        result = resolve_llm_params("unknown-model")
        assert result == {"drop_params": True}


# ------------------------------------------------------------------
# Support flag filtering tests
# ------------------------------------------------------------------


class TestSupportFlagFiltering:
    """Unsupported parameters are silently dropped."""

    def test_unsupported_param_dropped_from_user_override(self) -> None:
        meta = _make_metadata(supports_frequency_penalty=False)
        catalog = _mock_catalog(meta)
        result = resolve_llm_params(
            "test-model",
            user_overrides={"frequency_penalty": 0.5},
            catalog=catalog,
        )
        assert "frequency_penalty" not in result

    def test_unsupported_param_dropped_from_provider_config(self) -> None:
        meta = _make_metadata(supports_presence_penalty=False)
        catalog = _mock_catalog(meta)
        result = resolve_llm_params(
            "test-model",
            provider_config={"presence_penalty": 0.5},
            catalog=catalog,
        )
        assert "presence_penalty" not in result

    def test_unsupported_param_dropped_from_default(self) -> None:
        meta = _make_metadata(
            supports_seed=False,
            default_seed=42,
        )
        catalog = _mock_catalog(meta)
        result = resolve_llm_params("test-model", catalog=catalog)
        assert "seed" not in result

    def test_supported_param_passes_through(self) -> None:
        meta = _make_metadata(supports_seed=True)
        catalog = _mock_catalog(meta)
        result = resolve_llm_params(
            "test-model",
            user_overrides={"seed": 42},
            catalog=catalog,
        )
        assert result["seed"] == 42

    def test_no_metadata_assumes_supported(self) -> None:
        """When catalog returns None, params pass through optimistically."""
        result = resolve_llm_params(
            "unknown-model",
            user_overrides={"frequency_penalty": 0.5, "seed": 42},
        )
        assert result["frequency_penalty"] == 0.5
        assert result["seed"] == 42


# ------------------------------------------------------------------
# Range clamping tests
# ------------------------------------------------------------------


class TestRangeClamping:
    """Temperature and top_p are clamped to model ranges."""

    def test_temperature_clamped_above_max(self) -> None:
        meta = _make_metadata(temperature_range=[0.0, 1.0])
        catalog = _mock_catalog(meta)
        result = resolve_llm_params(
            "test-model",
            user_overrides={"temperature": 1.5},
            catalog=catalog,
        )
        assert result["temperature"] == 1.0

    def test_temperature_clamped_below_min(self) -> None:
        meta = _make_metadata(temperature_range=[0.1, 2.0])
        catalog = _mock_catalog(meta)
        result = resolve_llm_params(
            "test-model",
            user_overrides={"temperature": 0.0},
            catalog=catalog,
        )
        assert result["temperature"] == 0.1

    def test_temperature_within_range_unchanged(self) -> None:
        meta = _make_metadata(temperature_range=[0.0, 2.0])
        catalog = _mock_catalog(meta)
        result = resolve_llm_params(
            "test-model",
            user_overrides={"temperature": 1.0},
            catalog=catalog,
        )
        assert result["temperature"] == 1.0

    def test_top_p_clamped(self) -> None:
        meta = _make_metadata(top_p_range=[0.0, 0.9])
        catalog = _mock_catalog(meta)
        result = resolve_llm_params(
            "test-model",
            user_overrides={"top_p": 1.0},
            catalog=catalog,
        )
        assert result["top_p"] == 0.9

    def test_no_range_no_clamping(self) -> None:
        meta = _make_metadata(temperature_range=None)
        catalog = _mock_catalog(meta)
        result = resolve_llm_params(
            "test-model",
            user_overrides={"temperature": 5.0},
            catalog=catalog,
        )
        assert result["temperature"] == 5.0

    def test_no_metadata_no_clamping(self) -> None:
        result = resolve_llm_params(
            "unknown-model",
            user_overrides={"temperature": 5.0},
        )
        assert result["temperature"] == 5.0


# ------------------------------------------------------------------
# drop_params always present
# ------------------------------------------------------------------


class TestDropParams:
    """``drop_params=True`` is always in the result."""

    def test_drop_params_present_with_overrides(self) -> None:
        result = resolve_llm_params(
            "test-model",
            user_overrides={"temperature": 0.5},
        )
        assert result["drop_params"] is True

    def test_drop_params_present_empty(self) -> None:
        result = resolve_llm_params("test-model")
        assert result["drop_params"] is True


# ------------------------------------------------------------------
# max_tokens passthrough
# ------------------------------------------------------------------


class TestMaxTokens:
    """max_tokens has no support flag and passes through directly."""

    def test_max_tokens_from_user_override(self) -> None:
        result = resolve_llm_params(
            "test-model",
            user_overrides={"max_tokens": 8192},
        )
        assert result["max_tokens"] == 8192

    def test_max_tokens_from_provider_config(self) -> None:
        result = resolve_llm_params(
            "test-model",
            provider_config={"max_tokens": 2048},
        )
        assert result["max_tokens"] == 2048

    def test_max_tokens_omitted_when_not_set(self) -> None:
        result = resolve_llm_params("test-model")
        assert "max_tokens" not in result


# ------------------------------------------------------------------
# response_format passthrough
# ------------------------------------------------------------------


class TestResponseFormat:
    """response_format requires supports_response_format flag."""

    def test_response_format_passes_when_supported(self) -> None:
        meta = _make_metadata(supports_response_format=True)
        catalog = _mock_catalog(meta)
        fmt = {"type": "json_object"}
        result = resolve_llm_params(
            "test-model",
            user_overrides={"response_format": fmt},
            catalog=catalog,
        )
        assert result["response_format"] == fmt

    def test_response_format_dropped_when_unsupported(self) -> None:
        meta = _make_metadata(supports_response_format=False)
        catalog = _mock_catalog(meta)
        result = resolve_llm_params(
            "test-model",
            user_overrides={"response_format": {"type": "json_object"}},
            catalog=catalog,
        )
        assert "response_format" not in result

    def test_response_format_no_default_field(self) -> None:
        """response_format has no default_field, so it's never auto-populated."""
        meta = _make_metadata(supports_response_format=True)
        catalog = _mock_catalog(meta)
        result = resolve_llm_params("test-model", catalog=catalog)
        assert "response_format" not in result


# ------------------------------------------------------------------
# stop sequences
# ------------------------------------------------------------------


class TestStopSequences:
    """stop parameter follows standard resolution chain."""

    def test_stop_from_model_default(self) -> None:
        meta = _make_metadata(
            supports_stop=True,
            default_stop=["<|end|>"],
        )
        catalog = _mock_catalog(meta)
        result = resolve_llm_params("test-model", catalog=catalog)
        assert result["stop"] == ["<|end|>"]

    def test_stop_dropped_when_unsupported(self) -> None:
        meta = _make_metadata(
            supports_stop=False,
            default_stop=["<|end|>"],
        )
        catalog = _mock_catalog(meta)
        result = resolve_llm_params("test-model", catalog=catalog)
        assert "stop" not in result


# ------------------------------------------------------------------
# Catalog fuzzy lookup
# ------------------------------------------------------------------


class TestCatalogLookup:
    """Resolver uses get_model_fuzzy for prefix-stripping support."""

    def test_fuzzy_lookup_called(self) -> None:
        meta = _make_metadata()
        catalog = _mock_catalog(meta)
        resolve_llm_params("openai/gpt-4o", catalog=catalog)
        catalog.get_model_fuzzy.assert_called_once_with("openai/gpt-4o")


# ------------------------------------------------------------------
# Anthropic-like model (restricted params)
# ------------------------------------------------------------------


class TestAnthropicModel:
    """Simulates an Anthropic model with restricted penalty support."""

    def test_anthropic_model_drops_penalties(self) -> None:
        meta = _make_metadata(
            name="claude-3-5-sonnet",
            supports_frequency_penalty=False,
            supports_presence_penalty=False,
            temperature_range=[0.0, 1.0],
        )
        catalog = _mock_catalog(meta)
        result = resolve_llm_params(
            "claude-3-5-sonnet",
            user_overrides={
                "temperature": 0.8,
                "frequency_penalty": 0.5,
                "presence_penalty": 0.3,
                "seed": 42,
            },
            catalog=catalog,
        )
        assert result["temperature"] == 0.8
        assert result["seed"] == 42
        assert "frequency_penalty" not in result
        assert "presence_penalty" not in result


# ------------------------------------------------------------------
# Reasoning model (no temperature support)
# ------------------------------------------------------------------


class TestReasoningModel:
    """Simulates a reasoning model that doesn't accept temperature."""

    def test_reasoning_model_drops_temperature(self) -> None:
        meta = _make_metadata(
            name="o1",
            reasoning=True,
            supports_temperature=False,
            supports_top_p=False,
            supports_frequency_penalty=False,
            supports_presence_penalty=False,
            supports_seed=False,
            supports_stop=False,
        )
        catalog = _mock_catalog(meta)
        result = resolve_llm_params(
            "o1",
            user_overrides={
                "temperature": 0.5,
                "top_p": 0.9,
                "frequency_penalty": 0.1,
                "max_tokens": 4096,
            },
            catalog=catalog,
        )
        assert "temperature" not in result
        assert "top_p" not in result
        assert "frequency_penalty" not in result
        assert result["max_tokens"] == 4096
        assert result["drop_params"] is True


# ------------------------------------------------------------------
# Multi-param combined test
# ------------------------------------------------------------------


class TestCombinedResolution:
    """Verify multiple params resolve independently and correctly."""

    def test_mixed_sources(self) -> None:
        """temperature from user, top_p from provider, seed from default."""
        meta = _make_metadata(
            default_temperature=0.7,
            default_top_p=0.95,
            default_seed=123,
            supports_seed=True,
        )
        catalog = _mock_catalog(meta)
        result = resolve_llm_params(
            "test-model",
            user_overrides={"temperature": 0.3},
            provider_config={"top_p": 0.8},
            catalog=catalog,
        )
        assert result["temperature"] == 0.3
        assert result["top_p"] == 0.8
        assert result["seed"] == 123
        assert result["drop_params"] is True
