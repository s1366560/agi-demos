"""OAuth dispatch authorization and refresh transactions at the actual manager boundary."""

from __future__ import annotations

import asyncio
import time
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.services.marketplace_oauth import MarketplaceOAuth
from src.application.services.marketplace_oauth_runtime import (
    OAuthSandboxMCPServerManager,
    marketplace_activation,
)
from src.infrastructure.adapters.secondary.persistence.models import MCPServer, Project
from src.infrastructure.adapters.secondary.persistence.plugin_marketplace_models_v3 import (
    MarketplaceRecordV3,
)
from src.infrastructure.plugins import marketplace_snapshot_cache
from src.infrastructure.plugins.marketplace_credentials import open_transport
from src.infrastructure.plugins.marketplace_oauth_protocol import OAuthError
from src.tests.unit.application.services.test_marketplace_oauth import (
    consent,
    oauth as oauth_fixture,  # noqa: F401
)

pytestmark = pytest.mark.unit


@pytest.fixture
async def runtime(oauth_fixture, monkeypatch):  # noqa: F811
    service, fixture, row, _config = oauth_fixture
    callback = await consent(service, fixture)
    await service.callback(callback["state"][0], callback["code"][0])
    grant = await service.record("oauth_grant", "installation:demo")
    initial_access = open_transport(grant.payload["access_token"])
    grant.payload = {**grant.payload, "expires_at": time.time() - 1}
    resources = row.payload["package"]["resources"]
    row.payload = {
        **row.payload,
        "status": "enabled",
        "owned_servers": ["server"],
        "package": {
            **row.payload["package"],
            "resources": {
                **resources,
                "apps": {"fixture": {"mcp_server": "demo", "resource_uri": "ui://fixture/app"}},
            },
        },
    }
    await service.db.commit()
    async with service.db.bind.begin() as connection:
        await connection.run_sync(Project.__table__.create)
        await connection.run_sync(MCPServer.__table__.create)
    service.db.add(Project(id="project", tenant_id="tenant", name="Project", owner_id="user"))
    service.db.add(
        MCPServer(
            id="server",
            name="managed-demo",
            tenant_id="tenant",
            project_id="project",
            server_type="http",
            transport_config={"url": fixture.resource},
            enabled=True,
        )
    )
    await service.db.commit()
    sandbox = SimpleNamespace(
        execute_tool=AsyncMock(return_value={"content": []}),
        read_resource=AsyncMock(return_value="<html>protected app</html>"),
    )
    manager = OAuthSandboxMCPServerManager(db=service.db, sandbox_resource=sandbox)

    async def update_server(**kwargs):
        server = await service.db.get(MCPServer, kwargs["server_id"])
        server.transport_config = kwargs["transport_config"]
        server.runtime_status = "ready"
        return server

    manager.runtime_service = SimpleNamespace(update_server=AsyncMock(side_effect=update_server))

    @asynccontextmanager
    async def lease(*args, **kwargs):
        yield

    monkeypatch.setattr(marketplace_snapshot_cache, "lease_marketplace_snapshots", lease)
    return service, manager, sandbox, initial_access


async def test_refresh_rotation_survives_downstream_failure_and_outer_rollback(runtime):
    service, manager, sandbox, original = runtime
    sandbox.execute_tool.side_effect = RuntimeError("downstream operation failed")
    service.db.add(
        MarketplaceRecordV3(
            id="uncommitted",
            tenant_id="tenant",
            project_id="project",
            kind="unrelated",
            record_key="draft",
            payload={},
        )
    )
    with service.db.no_autoflush:
        result = await manager.call_tool("project", "managed-demo", "echo", {})
    assert result.is_error
    await service.db.rollback()
    async with AsyncSession(service.db.bind, expire_on_commit=False) as check:
        grant = await MarketplaceOAuth(check, "tenant", "project").record(
            "oauth_grant", "installation:demo"
        )
        assert open_transport(grant.payload["access_token"]) != original
        assert await check.get(MarketplaceRecordV3, "uncommitted") is None
    assert (
        await manager.read_resource("project", "ui://fixture/app", "managed-demo", "tenant")
        == "<html>protected app</html>"
    )
    sandbox.read_resource.assert_awaited_once()
    assert manager.runtime_service.update_server.await_count == 2


@pytest.mark.parametrize("status", ["disabled", "needs_configuration", "uninstalled"])
async def test_inactive_installation_cannot_dispatch_tools_or_apps(runtime, status):
    service, manager, sandbox, _ = runtime
    row = await service.installation("installation")
    row.payload = {**row.payload, "status": status}
    await service.db.commit()
    with pytest.raises(OAuthError, match="not_enabled"):
        await manager.call_tool("project", "managed-demo", "echo", {})
    with pytest.raises(OAuthError, match="not_enabled"):
        await manager.read_resource("project", "ui://fixture/app", "managed-demo", "tenant")
    with pytest.raises(OAuthError, match="not_enabled"):
        await manager.read_resource("project", "ui://fixture/app", tenant_id="tenant")
    sandbox.execute_tool.assert_not_awaited()
    sandbox.read_resource.assert_not_awaited()


async def test_other_tenant_and_disabled_server_never_reach_sandbox(runtime):
    service, manager, sandbox, _ = runtime
    with pytest.raises(OAuthError, match="scope_mismatch"):
        await manager.read_resource("project", "ui://fixture/app", "managed-demo", "another")
    server = await service.db.get(MCPServer, "server")
    server.enabled = False
    await service.db.commit()
    with pytest.raises(OAuthError, match="server_unavailable"):
        await manager.call_tool("project", "managed-demo", "echo", {})
    sandbox.execute_tool.assert_not_awaited()
    sandbox.read_resource.assert_not_awaited()


async def test_concurrent_refresh_waits_and_activation_bypass_is_task_scoped(runtime):
    service, manager, sandbox, _ = runtime
    row = await service.installation("installation")
    row.payload = {**row.payload, "status": "downloaded"}
    await service.db.commit()
    with marketplace_activation("tenant", "project", ["server"]):
        await manager.call_tool("project", "managed-demo", "__resources_read__", {})
    with pytest.raises(OAuthError, match="not_enabled"):
        await manager.call_tool("project", "managed-demo", "echo", {})
    sandbox.execute_tool.assert_awaited_once()
    entered, release = asyncio.Event(), asyncio.Event()

    async def refresh(*args):
        entered.set()
        await release.wait()

    manager._refresh = AsyncMock(side_effect=refresh)
    first = asyncio.create_task(manager.refresh("tenant", "project", "managed-demo"))
    await entered.wait()
    second = asyncio.create_task(manager.refresh("tenant", "project", "managed-demo"))
    await asyncio.sleep(0)
    assert not second.done()
    release.set()
    await asyncio.gather(first, second)
    assert manager._refresh.await_count == 2


async def test_connection_bound_caller_does_not_own_refresh_transaction(runtime):
    service, manager, _sandbox, original = runtime
    engine = service.db.bind
    manager.runtime_service.update_server = AsyncMock(
        return_value=SimpleNamespace(runtime_status="ready")
    )
    async with (
        engine.connect() as connection,
        connection.begin() as transaction,
        AsyncSession(connection, expire_on_commit=False) as outer,
    ):
        manager.db = outer
        await manager.call_tool("project", "managed-demo", "echo", {})
        await transaction.rollback()
    async with AsyncSession(engine, expire_on_commit=False) as check:
        grant = await MarketplaceOAuth(check, "tenant", "project").record(
            "oauth_grant", "installation:demo"
        )
        assert open_transport(grant.payload["access_token"]) != original


@pytest.mark.parametrize("factory", [False, True])
async def test_model_adapter_refreshes_and_enforces_scope_and_disabled_apps(
    runtime, monkeypatch, factory
):
    from src.application.services import marketplace_agent_mcp
    from src.infrastructure.mcp.sandbox_tool_adapter import (
        SandboxMCPServerToolAdapter,
        create_sandbox_mcp_server_tool,
    )

    service, manager, sandbox, original = runtime
    sandbox.get_sandbox_id = AsyncMock(return_value="sandbox")
    sandbox.execute_tool.return_value = {"content": [{"type": "text", "text": "echo accepted"}]}
    resolver = SimpleNamespace(resolve=lambda operation: SimpleNamespace(sandbox_manager=manager))
    scope = SimpleNamespace(tenant_id="tenant", project_id="project")
    operation = SimpleNamespace(
        context=SimpleNamespace(scope=scope), require=lambda alias: resolver
    )
    monkeypatch.setattr(marketplace_agent_mcp, "current_operation_context_v2", lambda: operation)
    raw = SimpleNamespace(call_tool=AsyncMock(), read_resource=AsyncMock())
    constructor = create_sandbox_mcp_server_tool if factory else SandboxMCPServerToolAdapter
    adapter = constructor(
        sandbox_adapter=raw,
        sandbox_id="sandbox",
        server_name="managed-demo",
        tool_info={"name": "echo", "_meta": {"ui": {"resourceUri": "ui://fixture/app"}}},
    )
    result = (
        await adapter.execute(SimpleNamespace(), value="model")
        if factory
        else await adapter.execute(value="model")
    )
    assert "echo accepted" in (result.output if factory else result)
    grant = await service.record("oauth_grant", "installation:demo")
    assert open_transport(grant.payload["access_token"]) != original
    assert await adapter.fetch_resource_html() == "<html>protected app</html>"
    raw.call_tool.assert_not_awaited()
    raw.read_resource.assert_not_awaited()
    scope.tenant_id = "other"
    with pytest.raises(OAuthError, match="scope_mismatch"):
        await adapter.fetch_resource_html()
    scope.tenant_id = "tenant"
    sandbox.get_sandbox_id.return_value = "other-sandbox"
    with pytest.raises(OAuthError, match="sandbox_scope_mismatch"):
        await adapter.fetch_resource_html()
    sandbox.get_sandbox_id.return_value = "sandbox"
    row = await service.installation("installation")
    row.payload = {**row.payload, "status": "disabled"}
    await service.db.commit()
    with pytest.raises(OAuthError, match="installation_not_enabled"):
        await adapter.fetch_resource_html()
    count = sandbox.execute_tool.await_count
    result = (
        await adapter.execute(SimpleNamespace(), value="blocked")
        if factory
        else await adapter.execute(value="blocked")
    )
    assert "installation_not_enabled" in (result.output if factory else result)
    assert sandbox.execute_tool.await_count == count


async def test_reenable_replaces_owned_transport_with_latest_grant(runtime):
    from src.application.services.plugin_marketplace_v3 import PluginMarketplaceV3

    service, manager, _sandbox, original = runtime
    row = await service.installation("installation")
    package = row.payload["package"]
    payload = {
        **row.payload,
        "id": "installation",
        "owned_skills": [],
        "status": "disabled",
        "package": {
            **package,
            "resources": {**package["resources"], "apps": {}, "skills": []},
        },
    }
    mcp = SimpleNamespace(
        runtime_service=manager.runtime_service,
        tool_cache=SimpleNamespace(invalidate=lambda tenant: None),
    )
    marketplace = PluginMarketplaceV3(service.db, "tenant", "project", mcp=mcp)
    await marketplace._activate(payload)
    assert payload["status"] == "enabled"
    updated = manager.runtime_service.update_server.call_args.kwargs
    assert updated["server_id"] == "server"
    assert updated["enabled"] is True
    actual = open_transport(updated["transport_config"]["headers"]["Authorization"])
    grant = await service.record("oauth_grant", "installation:demo")
    assert actual == "Bearer " + open_transport(grant.payload["access_token"])
    assert actual != "Bearer " + original
    assert "auth" not in updated["transport_config"]
