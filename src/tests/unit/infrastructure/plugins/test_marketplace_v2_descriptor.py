"""Public discovery must not bypass or disclose the V2 package trust envelope."""

from __future__ import annotations

import json

import pytest

from src.infrastructure.adapters.secondary.persistence.models import PlatformPluginPackageModel
from src.infrastructure.plugins.marketplace_v2_descriptor import describe_v2_package

pytestmark = pytest.mark.unit


def test_signed_descriptor_has_public_metadata_and_separate_install_strategy() -> None:
    package = PlatformPluginPackageModel(
        plugin_id="example",
        version="1.0.0",
        publisher="publisher",
        artifact_digest="a" * 64,
        manifest={"manifests": [{"permissions": ["network:connect", "network:connect"]}]},
        signature={"public_key_pem": "PRIVATE_TEST_ENVELOPE"},
        provenance={"builder_token": "PRIVATE_TEST_ENVELOPE"},
        revoked=False,
    )
    result = describe_v2_package(package)
    assert result["install_strategy"] == "signed-v2"
    assert result["permissions"] == ["network:connect"]
    assert result["compatible"] is True
    assert result["capabilities"] == []
    assert "PRIVATE_TEST_ENVELOPE" not in json.dumps(result)
    package.revoked = True
    assert describe_v2_package(package)["reasons"] == ["signed_package_revoked"]
