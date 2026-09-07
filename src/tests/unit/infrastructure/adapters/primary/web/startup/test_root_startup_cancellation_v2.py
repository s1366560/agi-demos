"""Cancellation during persistent startup closes its uninstalled host."""

import asyncio
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI

from src.infrastructure.adapters.primary.web.startup import plugin_runtime_v2 as startup

pytestmark = pytest.mark.unit


async def test_cancelled_configuration_preparation_closes_host(monkeypatch):
    close = AsyncMock()
    original = startup.PlatformPluginRuntimeHostV2

    def create(*args, **kwargs):
        host = original(*args, **kwargs)
        host.close = close
        return host

    monkeypatch.setattr(startup, "PlatformPluginRuntimeHostV2", create)
    monkeypatch.setattr(startup, "_last_good_distribution_v2", AsyncMock(return_value=None))
    monkeypatch.setattr(startup, "_latest_requested_distribution_v2", AsyncMock(return_value=None))
    monkeypatch.setattr(
        startup, "publish_configured_root_startup_v2", AsyncMock(side_effect=asyncio.CancelledError)
    )
    app = FastAPI()
    with pytest.raises(asyncio.CancelledError):
        await startup.initialize_plugin_runtime_v2(app, session_factory=lambda: None)
    close.assert_awaited_once()
    assert not hasattr(app.state, "platform_plugin_runtime_v2")
