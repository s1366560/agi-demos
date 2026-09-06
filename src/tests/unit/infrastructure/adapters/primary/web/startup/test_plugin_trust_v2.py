"""Deployment trust roots are explicit and fail before partially updating app state."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi import FastAPI

from src.configuration.config import Settings
from src.infrastructure.adapters.primary.web.startup.plugin_trust_v2 import (
    configure_plugin_trust_v2,
)

pytestmark = pytest.mark.unit


def _key(path):
    pem = (
        Ed25519PrivateKey.generate()
        .public_key()
        .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    )
    path.write_bytes(pem)
    return pem.decode("ascii")


def test_environment_trust_configuration_reaches_marketplace_app_state(tmp_path, monkeypatch):
    path = tmp_path / "publisher.pem"
    pem = _key(path)
    env = tmp_path / ".env"
    env.write_text("DATABASE_URL=postgresql://test:test@localhost/test\n")
    monkeypatch.setenv("PLUGIN_MARKETPLACE_TRUSTED_KEY_FILES", json.dumps([str(path), str(path)]))
    monkeypatch.setenv("PLUGIN_MARKETPLACE_ALLOWED_REGISTRIES", '["https://registry.example/"]')
    settings = Settings(_env_file=env)
    app = FastAPI()
    configure_plugin_trust_v2(
        app,
        key_files=settings.plugin_marketplace_trusted_key_files,
        allowed_registries=settings.plugin_marketplace_allowed_registries,
    )
    assert app.state.plugin_marketplace_trusted_public_keys_v2 == (pem,)
    assert app.state.plugin_marketplace_allowed_registries_v2 == frozenset(
        {"https://registry.example"}
    )


@pytest.mark.parametrize("invalid", ["missing", "malformed", "private", "registry"])
def test_invalid_trust_configuration_does_not_publish_partial_state(tmp_path, invalid):
    good = tmp_path / "good.pem"
    _key(good)
    bad = tmp_path / "bad.pem"
    if invalid == "malformed":
        bad.write_text("invalid public key")
    if invalid == "private":
        bad.write_bytes(
            Ed25519PrivateKey.generate().private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            )
        )
    app = FastAPI()
    app.state.plugin_marketplace_trusted_public_keys_v2 = ("existing",)
    with pytest.raises(ValueError):
        configure_plugin_trust_v2(
            app,
            key_files=(good,) if invalid == "registry" else (good, bad),
            allowed_registries=("http://external.example",) if invalid == "registry" else (),
        )
    assert app.state.plugin_marketplace_trusted_public_keys_v2 == ("existing",)
    assert not hasattr(app.state, "plugin_marketplace_allowed_registries_v2")


def test_empty_configuration_has_no_implicit_trust_or_external_registry():
    app = FastAPI()
    configure_plugin_trust_v2(app, key_files=(), allowed_registries=())
    assert app.state.plugin_marketplace_trusted_public_keys_v2 == ()
    assert app.state.plugin_marketplace_allowed_registries_v2 == frozenset()


async def test_real_lifespan_rejects_invalid_trust_before_database_startup(tmp_path, monkeypatch):
    from src.infrastructure.adapters.primary.web import main

    database_start = AsyncMock()
    monkeypatch.setattr(main, "initialize_database_schema", database_start)
    monkeypatch.setattr(
        main,
        "settings",
        SimpleNamespace(
            plugin_marketplace_trusted_key_files=(tmp_path / "missing.pem",),
            plugin_marketplace_allowed_registries=(),
        ),
    )
    with pytest.raises(ValueError, match="public-key file"):
        async with main.lifespan(FastAPI()):
            pytest.fail("invalid deployment trust reached application startup")
    database_start.assert_not_awaited()
