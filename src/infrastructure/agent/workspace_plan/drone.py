"""Compatibility shim for the Drone pipeline plugin provider.

The Drone implementation lives under ``.memstack/plugins/drone/provider.py``.
This module remains as a narrow import bridge for older tests and callers while
runtime provider resolution goes through the plugin registry.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

_PLUGIN_PROVIDER_PATH = (
    Path(__file__).resolve().parents[4] / ".memstack" / "plugins" / "drone" / "provider.py"
)


def _load_provider_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("_memstack_drone_provider", _PLUGIN_PROVIDER_PATH)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load Drone plugin provider: {_PLUGIN_PROVIDER_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_provider_module = _load_provider_module()
_provider_exports = (
    "DRONE_PROVIDER",
    "DroneCliClient",
    "DroneCliUnavailableError",
    "DroneClientProtocol",
    "DroneConfigurationError",
    "DronePipelineConfig",
    "DronePipelineProvider",
    "DroneRepositoryNotFoundError",
    "HttpDroneClient",
)
__all__ = [*_provider_exports, "time"]  # pyright: ignore[reportUnsupportedDunderAll]

for _name in _provider_exports:
    globals()[_name] = getattr(_provider_module, _name)

time = _provider_module.time
