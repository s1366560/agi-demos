"""Deployment archive memoization does not retain caller-owned mutable values."""

from dataclasses import replace
from unittest.mock import Mock, patch

import pytest

from src.application.services.installed_verified_bundle_loader_v2 import (
    MarketplacePublicationV2Error,
)
from src.application.services.scoped_installed_bundle_loader_v2 import ScopedInstalledBundleLoaderV2
from src.infrastructure.plugins.v2.bundle_archive import parse_bundle_archive_v2
from src.infrastructure.plugins.v2.production_bundle import production_bundle_sources_v2

pytestmark = pytest.mark.unit


async def test_local_archive_reuses_verification_but_checks_every_reference():
    source = production_bundle_sources_v2()
    sessions = Mock(side_effect=AssertionError("built-in archive needs no DB connection"))
    clients = Mock(side_effect=AssertionError("built-in archive needs no HTTP connection"))
    loader = ScopedInstalledBundleLoaderV2(
        session_factory=sessions,
        production_sources=source,
        trusted_public_keys=(),
        allowed_registries=frozenset(),
        http_client_factory=clients,
    )
    reference = source.desired_set.bundles[0]
    with patch(
        "src.application.services.scoped_installed_bundle_loader_v2.parse_bundle_archive_v2",
        wraps=parse_bundle_archive_v2,
    ) as verify:
        first = await loader(reference)
        first.manifest.layers[0].entries[0].config["tampered"] = True
        second = await loader(reference)
        assert "tampered" not in second.manifest.layers[0].entries[0].config
        assert verify.call_count == 1
        with pytest.raises(MarketplacePublicationV2Error, match="exact reference"):
            await loader(replace(reference, digest="sha256:" + "0" * 64))
    sessions.assert_not_called()
    clients.assert_not_called()
