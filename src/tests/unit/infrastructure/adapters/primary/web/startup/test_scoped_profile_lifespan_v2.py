"""Real application lifecycle ordering around scoped admission and ROOT retirement."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI

from src.configuration.workspace_core import WorkspaceCoreSettings
from src.infrastructure.adapters.primary.web import main
from src.infrastructure.adapters.primary.web.startup import scoped_profile_runtime_v2 as scoped

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("failure", ["none", "body", "cancel", "container", "scope-close"])
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

    async def root_close(*args):
        events.append("root-close")

    def scope_start(*args, **kwargs):
        events.append("scope-start")

    async def scope_close(*args):
        events.append("scope-close")
        if failure == "scope-close":
            raise RuntimeError("scope close failed")

    def container(**kwargs):
        if failure == "container":
            raise RuntimeError("container failed")
        return object()

    monkeypatch.setattr(main, "initialize_plugin_runtime_v2", root_start)
    monkeypatch.setattr(main, "shutdown_plugin_runtime_v2", root_close)
    monkeypatch.setattr(main, "initialize_container", container)
    monkeypatch.setattr(
        main,
        "PlatformPluginDeadlineReconcilerV2",
        lambda **kwargs: SimpleNamespace(start=lambda: None),
    )
    monkeypatch.setattr(scoped, "initialize_scoped_profile_runtime_v2", scope_start)
    monkeypatch.setattr(scoped, "shutdown_scoped_profile_runtime_v2", scope_close)

    async def run():
        async with main.lifespan(app):
            assert events == ["root-start", "scope-start"]
            if failure == "body":
                raise RuntimeError("body failed")
            if failure == "cancel":
                raise asyncio.CancelledError

    if failure == "none":
        await run()
    else:
        with pytest.raises(asyncio.CancelledError if failure == "cancel" else RuntimeError):
            await run()
    assert events == ["root-start", "scope-start", "scope-close", "root-close"]
