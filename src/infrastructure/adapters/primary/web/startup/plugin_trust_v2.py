"""Install operator-declared plugin trust roots before runtime startup."""

from collections.abc import Sequence
from pathlib import Path

from fastapi import FastAPI

from src.infrastructure.plugins.package_registry import load_plugin_trust_keys, normalize_registry


def configure_plugin_trust_v2(
    app: FastAPI, *, key_files: Sequence[Path], allowed_registries: Sequence[str]
) -> None:
    """Validate the full configuration before exposing either immutable trust value."""
    keys = load_plugin_trust_keys(key_files)
    registries = frozenset(normalize_registry(value) for value in allowed_registries)
    app.state.plugin_marketplace_trusted_public_keys_v2 = keys
    app.state.plugin_marketplace_allowed_registries_v2 = registries
