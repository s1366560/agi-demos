"""A foreground rollback must not apply another operation's newer request."""

import pytest

from src.application.services.marketplace_requested_recovery_v2 import (
    recover_live_requested_root_v2,
)
from src.tests.unit.application.services import (
    test_marketplace_live_requested_recovery_v2 as support,
)

pytestmark = pytest.mark.unit
live_requested = support.live_requested


async def test_republish_nonce_fence_preserves_other_pending_request(live_requested):
    app, host, factory, calls = live_requested
    before = await support._state(factory)
    kwargs = {
        "coordinator": app.state.platform_plugin_http_route_publication_v2,
        "session_factory": factory,
        "policy": app.state.platform_plugin_publication_policy_v2,
        "trusted_public_keys": (),
        "allowed_registries": frozenset(),
        "on_route_commit": None,
    }
    assert (
        await recover_live_requested_root_v2(
            **kwargs, expected_nonce=host.current_distribution.envelope.nonce
        )
        is False
    )
    assert calls == []
    assert await support._state(factory) == before
    assert (
        await recover_live_requested_root_v2(
            **kwargs, expected_nonce=before[0]["envelope"]["nonce"]
        )
        is True
    )
    assert calls == [host]
    assert host.current_distribution.to_payload() == before[0]
