"""Install operator-declared plugin trust roots before runtime startup."""

from collections.abc import Sequence
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from fastapi import FastAPI

from src.infrastructure.plugins.package_registry import normalize_registry


def configure_plugin_trust_v2(
    app: FastAPI, *, key_files: Sequence[Path], allowed_registries: Sequence[str]
) -> None:
    """Validate the full configuration before exposing either immutable trust value."""
    keys: list[str] = []
    for path in key_files:
        try:
            pem = path.read_text(encoding="utf-8")
            key = serialization.load_pem_public_key(pem.encode("utf-8"))
        except (OSError, ValueError, UnicodeError) as error:
            raise ValueError("plugin trust public-key file is unreadable or invalid") from error
        if not isinstance(key, Ed25519PublicKey):
            raise ValueError("plugin trust public key must be Ed25519")
        canonical = key.public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
        ).decode("ascii")
        if canonical not in keys:
            keys.append(canonical)
    registries = frozenset(normalize_registry(value) for value in allowed_registries)
    app.state.plugin_marketplace_trusted_public_keys_v2 = tuple(keys)
    app.state.plugin_marketplace_allowed_registries_v2 = registries
