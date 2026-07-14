"""Unit tests for model pricing loading and hot reload behavior."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from unittest.mock import Mock

import pytest

from src.infrastructure.agent.cost import pricing_loader


@pytest.fixture(autouse=True)
def reset_pricing_state(monkeypatch: pytest.MonkeyPatch) -> None:
    """Prevent pricing module caches from leaking between tests."""
    monkeypatch.setattr(pricing_loader, "_pricing_cache", {})
    monkeypatch.setattr(pricing_loader, "_default_cost_cache", None)
    monkeypatch.setattr(pricing_loader, "_file_mtime", 0.0)


def write_pricing(path: Path, *, input_cost: str = "1.25", output_cost: str = "5.00") -> None:
    """Write a minimal valid pricing document."""
    path.write_text(
        "\n".join(
            (
                "default:",
                '  input: "0.15"',
                '  output: "0.60"',
                "models:",
                "  model-a:",
                f'    input: "{input_cost}"',
                f'    output: "{output_cost}"',
            )
        ),
        encoding="utf-8",
    )


def test_get_pricing_file_path_points_to_bundled_yaml() -> None:
    """The default source should be colocated with the pricing loader."""
    path = pricing_loader._get_pricing_file_path()

    assert path.name == "model_pricing.yaml"
    assert path.parent == Path(pricing_loader.__file__).parent


def test_parse_model_cost_supports_optional_fields() -> None:
    """All supported pricing dimensions should be parsed as Decimals."""
    result = pricing_loader._parse_model_cost(
        {
            "input": "1.25",
            "output": 5,
            "cache_read": "0.10",
            "cache_write": "1.50",
            "reasoning": "7.25",
        }
    )

    assert result.input == Decimal("1.25")
    assert result.output == Decimal("5")
    assert result.cache_read == Decimal("0.10")
    assert result.cache_write == Decimal("1.50")
    assert result.reasoning == Decimal("7.25")


@pytest.mark.parametrize(
    "data",
    [
        {},
        {"input": "1.00"},
        {"output": "2.00"},
        {"input": None, "output": "2.00"},
    ],
)
def test_parse_model_cost_requires_input_and_output(data: dict[str, object]) -> None:
    """Incomplete model pricing should be rejected."""
    with pytest.raises(ValueError, match="must have 'input' and 'output'"):
        pricing_loader._parse_model_cost(data)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("input", ValueError("input conversion"), "Invalid Decimal value"),
        ("output", TypeError("output conversion"), "Invalid Decimal value"),
        ("cache_read", ValueError("cache read conversion"), "Invalid cache_read value"),
        ("cache_write", TypeError("cache write conversion"), "Invalid cache_write value"),
        ("reasoning", ValueError("reasoning conversion"), "Invalid reasoning value"),
    ],
)
def test_parse_model_cost_rejects_invalid_decimal_fields(
    field: str,
    value: Exception,
    message: str,
) -> None:
    """Invalid numeric representations should identify the offending dimension."""

    class FailingString:
        def __str__(self) -> str:
            raise value

    data: dict[str, object] = {"input": "1", "output": "2", field: FailingString()}

    with pytest.raises(ValueError, match=message):
        pricing_loader._parse_model_cost(data)


@pytest.mark.parametrize("field", ["input", "output", "cache_read", "cache_write", "reasoning"])
def test_parse_model_cost_normalizes_malformed_decimals(field: str) -> None:
    """Malformed decimals should consistently use the loader's public error type."""
    data: dict[str, object] = {"input": "1", "output": "2", field: "not-a-number"}

    with pytest.raises(ValueError, match="Invalid"):
        pricing_loader._parse_model_cost(data)


def test_parse_model_cost_accepts_zero_pricing() -> None:
    """Free models and cache dimensions are valid pricing configurations."""
    result = pricing_loader._parse_model_cost(
        {
            "input": 0,
            "output": "0",
            "cache_read": 0,
            "cache_write": "0.0",
            "reasoning": Decimal("0"),
        }
    )

    assert result.input == Decimal("0")
    assert result.output == Decimal("0")
    assert result.cache_read == Decimal("0")
    assert result.cache_write == Decimal("0.0")
    assert result.reasoning == Decimal("0")


@pytest.mark.parametrize("field", ["input", "output", "cache_read", "cache_write", "reasoning"])
@pytest.mark.parametrize("value", ["-0.01", "NaN", "Infinity", "-Infinity"])
def test_parse_model_cost_rejects_negative_or_non_finite_prices(
    field: str,
    value: str,
) -> None:
    """Pricing must be a finite, non-negative monetary value."""
    data: dict[str, object] = {"input": "1", "output": "2", field: value}

    with pytest.raises(ValueError, match="finite non-negative"):
        pricing_loader._parse_model_cost(data)


def test_load_pricing_from_file_returns_models_and_default(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A valid YAML document should produce model and default costs."""
    pricing_file = tmp_path / "pricing.yaml"
    pricing_file.write_text(
        """
default:
  input: "0.15"
  output: "0.60"
models:
  model-a:
    input: "1.25"
    output: "5.00"
    cache_read: "0.10"
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setattr(pricing_loader, "_get_pricing_file_path", lambda: pricing_file)

    models, default = pricing_loader._load_pricing_from_file()

    assert models["model-a"].input == Decimal("1.25")
    assert models["model-a"].cache_read == Decimal("0.10")
    assert default.output == Decimal("0.60")


def test_load_pricing_from_file_requires_existing_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A missing pricing document should fail explicitly."""
    missing = tmp_path / "missing.yaml"
    monkeypatch.setattr(pricing_loader, "_get_pricing_file_path", lambda: missing)

    with pytest.raises(FileNotFoundError, match="Pricing file not found"):
        pricing_loader._load_pricing_from_file()


@pytest.mark.parametrize(
    ("content", "message"),
    [
        ("default: [", "Invalid YAML"),
        ("- item", "must contain a YAML dictionary"),
        ("default: []\nmodels: {}", "'default' section must be a dictionary"),
        (
            "default: {input: '1', output: '2'}\nmodels: []",
            "'models' section must be a dictionary",
        ),
        (
            "default: {input: '1', output: '2'}\nmodels: {model-a: []}",
            "Model 'model-a' cost data must be a dictionary",
        ),
    ],
)
def test_load_pricing_from_file_rejects_malformed_documents(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    content: str,
    message: str,
) -> None:
    """Malformed YAML structures should fail with actionable errors."""
    pricing_file = tmp_path / "pricing.yaml"
    pricing_file.write_text(content, encoding="utf-8")
    monkeypatch.setattr(pricing_loader, "_get_pricing_file_path", lambda: pricing_file)

    with pytest.raises(ValueError, match=message):
        pricing_loader._load_pricing_from_file()


def test_get_model_costs_loads_once_until_mtime_changes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The hot reload cache should refresh only after the source mtime changes."""
    pricing_file = tmp_path / "pricing.yaml"
    write_pricing(pricing_file)
    mtime = {"value": 1.0}
    load = Mock(wraps=pricing_loader._load_pricing_from_file)
    monkeypatch.setattr(pricing_loader, "_get_pricing_file_path", lambda: pricing_file)
    monkeypatch.setattr(pricing_loader.os.path, "getmtime", lambda path: mtime["value"])
    monkeypatch.setattr(pricing_loader, "_load_pricing_from_file", load)

    first = pricing_loader.get_model_costs()
    second = pricing_loader.get_model_costs()
    write_pricing(pricing_file, input_cost="2.50", output_cost="10.00")
    mtime["value"] = 2.0
    third = pricing_loader.get_model_costs()

    assert first is second
    assert first["model-a"].input == Decimal("1.25")
    assert third["model-a"].input == Decimal("2.50")
    assert load.call_count == 2
    assert pricing_loader._file_mtime == 2.0


def test_get_model_costs_skips_reload_when_other_thread_refreshed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The locked double-check should honor a cache refreshed by another caller."""
    sentinel = {"existing": object()}
    pricing_loader._pricing_cache = sentinel  # type: ignore[assignment]
    pricing_loader._file_mtime = 1.0
    getmtime = Mock(side_effect=[2.0, 1.0])
    load = Mock(side_effect=AssertionError("must not reload"))
    monkeypatch.setattr(pricing_loader.os.path, "getmtime", getmtime)
    monkeypatch.setattr(pricing_loader, "_load_pricing_from_file", load)

    result = pricing_loader.get_model_costs()

    assert result is sentinel
    load.assert_not_called()


def test_get_model_costs_wraps_initial_stat_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """A pricing path stat error should surface as FileNotFoundError."""
    monkeypatch.setattr(
        pricing_loader.os.path,
        "getmtime",
        Mock(side_effect=PermissionError("denied")),
    )

    with pytest.raises(FileNotFoundError, match="Cannot access pricing file: denied"):
        pricing_loader.get_model_costs()


def test_get_model_costs_wraps_locked_stat_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """A stat failure during the locked recheck should also be normalized."""
    monkeypatch.setattr(
        pricing_loader.os.path,
        "getmtime",
        Mock(side_effect=[2.0, PermissionError("locked denial")]),
    )

    with pytest.raises(FileNotFoundError, match="Cannot access pricing file: locked denial"):
        pricing_loader.get_model_costs()


def test_get_default_cost_returns_loaded_default(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Unknown models should use the default from the current pricing document."""
    pricing_file = tmp_path / "pricing.yaml"
    write_pricing(pricing_file)
    monkeypatch.setattr(pricing_loader, "_get_pricing_file_path", lambda: pricing_file)
    monkeypatch.setattr(pricing_loader.os.path, "getmtime", lambda path: 1.0)

    result = pricing_loader.get_default_cost()

    assert result.input == Decimal("0.15")
    assert result.output == Decimal("0.60")


def test_get_default_cost_uses_fallback_when_cache_is_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The defensive fallback should remain available if loading yields no default."""
    monkeypatch.setattr(pricing_loader, "get_model_costs", dict)
    pricing_loader._default_cost_cache = None

    result = pricing_loader.get_default_cost()

    assert result.input == Decimal("0.15")
    assert result.output == Decimal("0.60")
