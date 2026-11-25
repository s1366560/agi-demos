"""Real application lifecycle ordering around scoped admission and ROOT retirement."""

import asyncio
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI

from src.application.services.marketplace_cache_recovery import MarketplaceCacheRecovery
from src.application.services.memory_update_dispatch import MemoryUpdateDispatcher
from src.configuration.workspace_core import WorkspaceCoreSettings
from src.infrastructure.adapters.primary.web import main
from src.infrastructure.adapters.primary.web.startup import scoped_profile_runtime_v2 as scoped

pytestmark = pytest.mark.unit


def _track_recovery(monkeypatch, events, failure):
    def memory_start(_dispatcher):
        events.append("memory-start")
        if failure == "memory-start":
            raise RuntimeError("memory start failed")

    async def memory_close(_dispatcher):
        events.append("memory-close")

    monkeypatch.setattr(MemoryUpdateDispatcher, "start", memory_start)
    monkeypatch.setattr(MemoryUpdateDispatcher, "aclose", memory_close)
    monkeypatch.setattr(MarketplaceCacheRecovery, "start", lambda _recovery: None)
    monkeypatch.setattr(main, "recovery_loop", lambda _sessions: nullcontext())
    monkeypatch.setattr(main, "worker_recovery", lambda _enabled: nullcontext())


@pytest.mark.parametrize(
    "failure", ["none", "body", "cancel", "container", "memory-start", "scope-close"]
)
async def test_real_lifespan_closes_scoped_before_root_even_on_failure(monkeypatch, failure):
    events = []
    app = FastAPI()
    app.state.workspace_core_settings = WorkspaceCoreSettings(_env_file=None)
    monkeypatch.setattr(main, "initialize_database_schema", AsyncMock())
    monkeypatch.setattr(main, "initialize_llm_providers", AsyncMock())
    monkeypatch.setattr(main, "initialize_redis_client", AsyncMock(return_value=None))
    monkeypatch.setattr(
        main,
        "settings",
        main.settings.model_copy(
            update={
                "environment": "development",
                "plugin_v2_required_data_plane_ids": "",
                "plugin_marketplace_trusted_key_files": (),
                "plugin_marketplace_allowed_registries": (),
            }
        ),
    )

    async def root_start(*args, **kwargs):
        events.append("root-start")
        app.state.platform_plugin_runtime_v2 = object()
        app.state.platform_plugin_http_route_publication_v2 = object()

    async def root_close(*args):
        events.append("root-close")

    def scope_start(app, **kwargs):
        events.append("scope-start")
        app.state.scoped_profile_runtime_v2 = object()
        return app.state.scoped_profile_runtime_v2

    async def scope_close(*args):
        events.append("scope-close")
        if failure == "scope-close":
            raise RuntimeError("scope close failed")

    def container(**kwargs):
        if failure == "container":
            raise RuntimeError("container failed")
        return object()

    _track_recovery(monkeypatch, events, failure)
    monkeypatch.setattr(main, "initialize_plugin_runtime_v2", root_start)
    monkeypatch.setattr(main, "shutdown_plugin_runtime_v2", root_close)
    monkeypatch.setattr(main, "initialize_container", container)
    monkeypatch.setattr(
        main,
        "PlatformPluginDeadlineReconcilerV2",
        lambda **kwargs: SimpleNamespace(start=lambda: None),
    )
    monkeypatch.setattr(
        main,
        "MarketplaceReceiptRecoveryV2",
        lambda **kwargs: SimpleNamespace(start=lambda: events.append("receipt-start")),
    )
    monkeypatch.setattr(scoped, "initialize_scoped_profile_runtime_v2", scope_start)
    monkeypatch.setattr(scoped, "shutdown_scoped_profile_runtime_v2", scope_close)

    async def run():
        async with main.lifespan(app):
            assert events == ["root-start", "scope-start", "receipt-start", "memory-start"]
            if failure == "body":
                raise RuntimeError("body failed")
            if failure == "cancel":
                raise asyncio.CancelledError

    if failure == "none":
        await run()
    else:
        with pytest.raises(asyncio.CancelledError if failure == "cancel" else RuntimeError):
            await run()
    recovery_events = (
        [] if failure == "container" else ["receipt-start", "memory-start", "memory-close"]
    )
    assert events == ["root-start", "scope-start", *recovery_events, "scope-close", "root-close"]
