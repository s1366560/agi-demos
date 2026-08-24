"""Generic channel implementation module loader.

Loads stable channel modules from the infrastructure package using ``importlib``
so application-layer consumers remain decoupled from specific implementations.

Usage::

    from src.infrastructure.adapters.secondary.channels.channel_plugin_loader import (
        load_channel_module,
    )

    client_mod = load_channel_module("feishu", "client")
    FeishuClient = client_mod.FeishuClient

To register a custom channel whose implementation files live outside the default
directory tree, call :func:`register_channel_plugin` before first use.
"""

from __future__ import annotations

import importlib.util
import logging
import sys
from functools import lru_cache
from pathlib import Path
from types import ModuleType

_SIBLING_FQN_PREFIX: dict[str, str] = {
    "feishu": "feishu",
}

logger = logging.getLogger(__name__)

_CHANNEL_MODULE_REGISTRY: dict[str, Path] = {
    "feishu": Path(__file__).resolve().parent / "feishu",
}


def register_channel_plugin(channel: str, plugin_dir: Path) -> None:
    """Register (or override) the plugin directory for *channel*.

    This also invalidates the LRU cache so that subsequent calls to
    :func:`load_channel_module` pick up the new path.
    """
    _CHANNEL_MODULE_REGISTRY[channel] = plugin_dir
    load_channel_module.cache_clear()


@lru_cache(maxsize=64)
def load_channel_module(channel: str, submodule: str) -> ModuleType:
    """Load and return a plugin sub-module for the given *channel*.

    Parameters
    ----------
    channel:
        Channel identifier, e.g. ``"feishu"``.
    submodule:
        Python file name (without ``.py``), e.g. ``"client"``.

    Returns
    -------
    ModuleType
        The loaded module object.

    Raises
    ------
    KeyError
        If *channel* has not been registered.
    FileNotFoundError
        If the plugin file does not exist on disk.
    ImportError
        If the module spec cannot be created.
    """
    implementation_dir = _CHANNEL_MODULE_REGISTRY.get(channel)
    if implementation_dir is None:
        msg = (
            f"Unknown channel {channel!r}. Registered channels: {sorted(_CHANNEL_MODULE_REGISTRY)}"
        )
        raise KeyError(msg)

    file_path = implementation_dir / f"{submodule}.py"
    if not file_path.exists():
        msg = f"Channel implementation module not found: {file_path}"
        raise FileNotFoundError(msg)

    module_fqn = f"memstack_plugins_{channel}.{submodule}"

    # Compute the sibling FQN that _load_sibling() in plugin.py would use
    # (e.g. "feishu_adapter") so we can share the same module object.
    sibling_prefix = _SIBLING_FQN_PREFIX.get(channel, channel)
    sibling_fqn = f"{sibling_prefix}_{submodule}"

    # Fast-path: already loaded by _load_sibling() or a prior call.
    if sibling_fqn in sys.modules:
        mod = sys.modules[sibling_fqn]
        sys.modules[module_fqn] = mod
        _ensure_parent_package(channel, implementation_dir)
        return mod
    if module_fqn in sys.modules:
        return sys.modules[module_fqn]

    spec = importlib.util.spec_from_file_location(module_fqn, file_path)
    if spec is None or spec.loader is None:
        msg = f"Cannot create module spec for {file_path}"
        raise ImportError(msg)

    module = importlib.util.module_from_spec(spec)

    # Register under both FQNs BEFORE exec so that circular references
    # within plugin code resolve correctly.
    sys.modules[module_fqn] = module
    sys.modules[sibling_fqn] = module

    # Ensure a parent package exists so unittest.mock.patch() can resolve
    # dotted names like "memstack_plugins_feishu.adapter.threading".
    _ensure_parent_package(channel, implementation_dir)

    spec.loader.exec_module(module)
    return module


def _ensure_parent_package(channel: str, plugin_dir: Path) -> None:
    """Register a synthetic parent package ``memstack_plugins_{channel}``."""
    parent_fqn = f"memstack_plugins_{channel}"
    if parent_fqn not in sys.modules:
        parent_pkg = ModuleType(parent_fqn)
        parent_pkg.__path__ = [str(plugin_dir)]
        parent_pkg.__package__ = parent_fqn
        sys.modules[parent_fqn] = parent_pkg
