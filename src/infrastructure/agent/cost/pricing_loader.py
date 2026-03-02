"""Pricing loader with hot-reload support for model costs."""

from __future__ import annotations

import os
import threading
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

if TYPE_CHECKING:
    from .tracker import ModelCost

# Type alias for cost dictionary
type CostDict = dict[str, "ModelCost"]

# Module-level state
_pricing_cache: CostDict = {}
_default_cost_cache: ModelCost | None = None
_file_mtime: float = 0.0
_lock = threading.Lock()


def _get_pricing_file_path() -> Path:
    """Get the absolute path to the pricing YAML file."""
    current_dir = Path(__file__).parent
    return current_dir / "model_pricing.yaml"


def _load_pricing_from_file() -> tuple[CostDict, ModelCost]:
    """
    Load pricing data from YAML file and convert to ModelCost instances.

    Returns:
        Tuple of (model_costs_dict, default_cost)

    Raises:
        FileNotFoundError: If pricing file not found
        ValueError: If pricing file is malformed
    """
    # Import here to avoid circular import

    file_path = _get_pricing_file_path()

    if not file_path.exists():
        raise FileNotFoundError(f"Pricing file not found: {file_path}")

    try:
        with open(file_path) as f:
            data: dict[str, object] = yaml.safe_load(f)
    except yaml.YAMLError as e:
        raise ValueError(f"Invalid YAML in pricing file: {e}") from e

    if not isinstance(data, dict):
        raise ValueError("Pricing file must contain a YAML dictionary")

    # Load default pricing
    default_data_obj = data.get("default", {})
    if not isinstance(default_data_obj, dict):
        raise ValueError("'default' section must be a dictionary")
    default_data: dict[str, object] = default_data_obj
    default_cost = _parse_model_cost(default_data)

    # Load all model costs
    models_data_obj = data.get("models", {})
    if not isinstance(models_data_obj, dict):
        raise ValueError("'models' section must be a dictionary")
    models_data: dict[str, object] = models_data_obj

    model_costs: CostDict = {}
    for model_name, cost_data in models_data.items():
        if not isinstance(cost_data, dict):
            raise ValueError(
                f"Model '{model_name}' cost data must be a dictionary"
            )
        model_costs[model_name] = _parse_model_cost(cost_data)

    return model_costs, default_cost

def _parse_model_cost(data: dict[str, object]) -> ModelCost:
    """
    Parse a single model cost configuration from dictionary.

    Args:
        data: Dictionary with cost fields (input, output, cache_read, etc.)

    Returns:
        ModelCost instance with Decimal values

    Raises:
        ValueError: If required fields are missing or invalid
    """
    # Import here to avoid circular import
    from .tracker import ModelCost

    input_str = data.get("input")
    output_str = data.get("output")

    if not input_str or not output_str:
        msg = "Model cost must have 'input' and 'output' fields"
        raise ValueError(msg)

    try:
        input_cost = Decimal(str(input_str))
        output_cost = Decimal(str(output_str))
    except (ValueError, TypeError) as e:
        raise ValueError(f"Invalid Decimal value: {e}") from e

    # Parse optional fields
    cache_read = None
    if "cache_read" in data and data["cache_read"] is not None:
        try:
            cache_read = Decimal(str(data["cache_read"]))
        except (ValueError, TypeError) as e:
            raise ValueError(f"Invalid cache_read value: {e}") from e

    cache_write = None
    if "cache_write" in data and data["cache_write"] is not None:
        try:
            cache_write = Decimal(str(data["cache_write"]))
        except (ValueError, TypeError) as e:
            raise ValueError(f"Invalid cache_write value: {e}") from e

    reasoning = None
    if "reasoning" in data and data["reasoning"] is not None:
        try:
            reasoning = Decimal(str(data["reasoning"]))
        except (ValueError, TypeError) as e:
            raise ValueError(f"Invalid reasoning value: {e}") from e

    return ModelCost(
        input=input_cost,
        output=output_cost,
        cache_read=cache_read,
        cache_write=cache_write,
        reasoning=reasoning,
    )


def get_model_costs() -> CostDict:
    """
    Get all model costs with hot-reload support.

    Checks file modification time on each call. If the file has been
    modified, reloads pricing data. Otherwise returns cached data.

    Returns:
        Dictionary mapping model names to ModelCost configurations

    Raises:
        FileNotFoundError: If pricing file not found
        ValueError: If pricing file is malformed
    """
    global _pricing_cache, _default_cost_cache, _file_mtime

    file_path = _get_pricing_file_path()

    # Get current file modification time
    try:
        current_mtime = os.path.getmtime(file_path)
    except OSError as e:
        raise FileNotFoundError(f"Cannot access pricing file: {e}") from e

    # Check if file has changed
    if current_mtime != _file_mtime:
        with _lock:
            # Double-check after acquiring lock
            try:
                current_mtime = os.path.getmtime(file_path)
            except OSError as e:
                raise FileNotFoundError(f"Cannot access pricing file: {e}") from e

            if current_mtime != _file_mtime:
                # Reload pricing
                _pricing_cache, _default_cost_cache = _load_pricing_from_file()
                _file_mtime = current_mtime

    return _pricing_cache




def get_default_cost() -> ModelCost:
    """
    Get the default model cost for unknown models.

    Ensures pricing is loaded via hot-reload check.

    Returns:
        Default ModelCost configuration
    """
    # Trigger reload check
    _ = get_model_costs()

    if _default_cost_cache is None:
        # Fallback (should never happen if get_model_costs succeeds)
        from .tracker import ModelCost

        return ModelCost(
            input=Decimal("0.15"),
            output=Decimal("0.60"),
        )

    return _default_cost_cache
