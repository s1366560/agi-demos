"""Persistent ROOT startup must bind verified archive bytes on both startup branches."""

from dataclasses import replace

import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.application.services.scoped_installed_bundle_loader_v2 import ScopedInstalledBundleLoaderV2
from src.infrastructure.adapters.primary.web.startup import plugin_runtime_v2 as startup
from src.infrastructure.plugins.v2.runtime import RuntimeV2Error

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("durable", [False, True])
async def test_startup_rejects_archive_execution_mismatch_before_routes(
    db_session, monkeypatch, durable
):
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    if durable:
        previous = FastAPI()
        try:
            await startup.initialize_plugin_runtime_v2(previous, session_factory=factory)
        finally:
            await startup.shutdown_plugin_runtime_v2(previous)
    original = ScopedInstalledBundleLoaderV2.__call__

    async def corrupted_trust_result(self, reference):
        archive = await original(self, reference)
        # Inject corruption after archive verification to distinguish the actual execution gate.
        return replace(
            archive,
            artifacts=dict.fromkeys(archive.artifacts, b"wrong verified bytes"),
        )

    monkeypatch.setattr(ScopedInstalledBundleLoaderV2, "__call__", corrupted_trust_result)
    route_calls = []

    def unexpected_routes(**kwargs):
        route_calls.append(kwargs)
        raise AssertionError("artifact mismatch must be rejected before route staging")

    monkeypatch.setattr(startup, "build_builtin_route_graph_v2", unexpected_routes)
    app = FastAPI()
    try:
        with pytest.raises(RuntimeV2Error, match="executable bytes differ"):
            await startup.initialize_plugin_runtime_v2(app, session_factory=factory)
        assert route_calls == []
        assert getattr(app.state, "platform_plugin_runtime_v2", None) is None
    finally:
        await startup.shutdown_plugin_runtime_v2(app)
