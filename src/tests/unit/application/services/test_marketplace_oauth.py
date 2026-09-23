"""Real protocol, encrypted persistence and isolation for marketplace OAuth."""

from __future__ import annotations

import importlib.util
import json
import re
import threading
import time
from http.server import ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from src.application.services.marketplace_oauth import MarketplaceOAuth
from src.infrastructure.adapters.secondary.persistence.plugin_marketplace_models_v3 import (
    MarketplaceRecordV3,
)
from src.infrastructure.plugins import marketplace_credentials
from src.infrastructure.plugins.marketplace_oauth_protocol import OAuthError
from src.infrastructure.security.encryption_service import EncryptionService

pytestmark = pytest.mark.unit


@pytest.fixture
async def oauth(monkeypatch, tmp_path):
    path = (
        Path(__file__).resolve().parents[5] / "plugins/marketplace-examples/oauth-fixture/server.py"
    )
    spec = importlib.util.spec_from_file_location("marketplace_oauth_fixture", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    fixture = module.Fixture("http://127.0.0.1:0")
    server = ThreadingHTTPServer(("127.0.0.1", 0), module.handler(fixture))
    fixture.origin = f"http://127.0.0.1:{server.server_port}"
    fixture.resource = fixture.origin + "/mcp"
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.setenv("PLUGIN_MARKETPLACE_OAUTH_TEST_ORIGIN", fixture.origin)
    encryption = EncryptionService("12" * 32)
    monkeypatch.setattr(
        marketplace_credentials,
        "get_settings",
        lambda: SimpleNamespace(llm_encryption_key="12" * 32),
    )
    monkeypatch.setattr(marketplace_credentials, "get_encryption_service", lambda: encryption)
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'oauth.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(MarketplaceRecordV3.__table__.create)
    async with AsyncSession(engine, expire_on_commit=False) as db:
        config = {
            "url": fixture.resource,
            "oauth": {"client_id": "marketplace-fixture", "scopes": ["mcp:tools"]},
        }
        row = MarketplaceRecordV3(
            id="installation",
            tenant_id="tenant",
            project_id="project",
            kind="installation",
            record_key="plugin",
            payload={
                "id": "installation",
                "version": "1.0.0",
                "status": "downloaded",
                "package": {
                    "digest": "sha256:test",
                    "resources": {"mcp_servers": {"demo": config}},
                },
            },
        )
        db.add(row)
        await db.flush()
        yield MarketplaceOAuth(db, "tenant", "project"), fixture, row, config
    await engine.dispose()
    server.shutdown()
    server.server_close()
    thread.join()


async def consent(service, fixture, *, key="start", decision="allow"):
    response = await service.start(
        "installation", "demo", "user", "http://127.0.0.1:54321/callback", key, {}
    )
    assert response["status"] == "authorizing"
    async with httpx.AsyncClient() as client:
        page = await client.get(response["authorization_url"])
        ticket = re.search(r'name="ticket" value="([^"]+)"', page.text)[1]
        redirect = await client.post(
            fixture.origin + "/consent",
            data={
                "ticket": ticket,
                "username": "fixture-user",
                "password": "fixture-password",
                "decision": decision,
            },
        )
    return parse_qs(urlsplit(redirect.headers["location"]).query)


async def test_real_pkce_callback_encryption_tool_app_refresh_revoke(oauth):
    service, fixture, row, config = oauth
    callback = await consent(service, fixture)
    state, code = callback["state"][0], callback["code"][0]
    assert (await service.callback(state, code))["status"] == "connected"
    grant = await service.record("oauth_grant", "installation:demo")
    bearer = await service.bearer("installation", "demo", config)
    assert bearer[7:] not in json.dumps(grant.payload)
    async with httpx.AsyncClient() as client:
        result = await client.post(
            fixture.resource,
            headers={"Authorization": bearer},
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": "echo", "arguments": {"message": "REAL_OAUTH"}},
            },
        )
        assert result.status_code == 200
        app = await client.post(
            fixture.resource,
            headers={"Authorization": bearer},
            json={
                "jsonrpc": "2.0",
                "id": 2,
                "method": "resources/read",
                "params": {"uri": "ui://fixture/app"},
            },
        )
        assert app.status_code == 200
    grant.payload = {**grant.payload, "expires_at": time.time() - 1}
    connection = await service.status(row.id, "demo")
    assert connection["status"] == "connected"
    assert connection["expires_at"] < time.time()
    refreshed = await service.bearer(row.id, "demo", config)
    assert refreshed != bearer
    assert (await service.disconnect(row.id, "demo"))["status"] == "not_connected"
    assert await service.record("oauth_grant", "installation:demo") is None
    with pytest.raises(OAuthError, match="used"):
        await service.callback(state, code)


async def test_scope_state_cancel_and_version_binding(oauth):
    service, fixture, row, _ = oauth
    callback = await consent(service, fixture)
    state, code = callback["state"][0], callback["code"][0]
    with pytest.raises(OAuthError, match="state_invalid"):
        await MarketplaceOAuth(service.db, "other", "project").callback(state, code)
    with pytest.raises(OAuthError, match="state_invalid"):
        await service.callback(state + "tampered", code)
    await service.disconnect(row.id, "demo", cancel_only=True)
    with pytest.raises(OAuthError, match="used"):
        await service.callback(state, code)
    callback = await consent(service, fixture, key="another")
    row.payload = {**row.payload, "version": "2.0.0"}
    with pytest.raises(OAuthError, match="version_changed"):
        await service.callback(callback["state"][0], callback["code"][0])
    challenge = await service.record("oauth_challenge", callback["state"][0].partition(".")[0])
    assert "verifier" not in challenge.payload


async def test_denial_resource_binding_and_idempotency(oauth):
    service, fixture, row, config = oauth
    callback = await consent(service, fixture, decision="deny")
    assert (await service.callback(callback["state"][0], None, "access_denied"))[
        "status"
    ] == "error"
    with pytest.raises(OAuthError, match="idempotency"):
        await service.start(
            row.id, "demo", "different-user", "http://127.0.0.1:54321/callback", "start", {}
        )
    callback = await consent(service, fixture, key="retry")
    await service.callback(callback["state"][0], callback["code"][0])
    with pytest.raises(OAuthError, match="reauthorization"):
        await service.bearer(row.id, "demo", {**config, "url": fixture.origin + "/other-resource"})


async def test_callback_rechecks_installation_state_and_resource(oauth):
    service, fixture, row, _ = oauth
    callback = await consent(service, fixture)
    row.payload = {**row.payload, "status": "enabled"}
    with pytest.raises(OAuthError, match="state_changed"):
        await service.callback(callback["state"][0], callback["code"][0])
    with pytest.raises(OAuthError, match="used"):
        await service.callback(callback["state"][0], callback["code"][0])


@pytest.mark.parametrize(
    "overrides,reason",
    [
        ({"expires_in": float("inf")}, "expiry_invalid"),
        ({"expires_in": float("nan")}, "expiry_invalid"),
        ({"scope": ["mcp:tools"]}, "scope_invalid"),
        ({"refresh_token": {}}, "refresh_token_invalid"),
        (
            {"access_token": "bad\\r\\nheader".replace("\\r", "\r").replace("\\n", "\n")},
            "access_token_invalid",
        ),
    ],
)
async def test_malformed_provider_tokens_fail_as_safe_protocol_errors(overrides, reason):
    from unittest.mock import AsyncMock

    from src.infrastructure.plugins.marketplace_oauth_protocol import OAuthHTTP

    protocol = OAuthHTTP()
    protocol.request = AsyncMock(
        return_value=(
            200,
            {},
            {"access_token": "example", "token_type": "Bearer", "expires_in": 3600, **overrides},
        )
    )
    with pytest.raises(OAuthError, match=reason):
        await protocol.token(
            "https://provider.example/token", {"resource": "https://service.example/mcp"}
        )


@pytest.mark.parametrize("transport", ["sse", "websocket", "stdio", "streamable-http", "http"])
def test_existing_oauth_installation_rejects_unsupported_transport(transport):
    from types import SimpleNamespace

    from src.application.services.marketplace_oauth import MarketplaceOAuth
    from src.infrastructure.plugins.marketplace_oauth_protocol import OAuthError

    row = SimpleNamespace(
        payload={
            "package": {
                "resources": {
                    "mcp_servers": {
                        "protected": {
                            "type": transport,
                            "url": "https://example.com/mcp",
                            "oauth": {},
                            **({"command": "python"} if transport == "http" else {}),
                        }
                    }
                }
            }
        }
    )
    with pytest.raises(OAuthError, match="oauth_requires_streamable_http"):
        MarketplaceOAuth.server(row, "protected")


async def test_status_distinguishes_refreshable_expiry_from_invalid_grant(oauth, monkeypatch):
    from unittest.mock import AsyncMock

    service, fixture, row, config = oauth
    callback = await consent(service, fixture)
    await service.callback(callback["state"][0], callback["code"][0])
    grant = await service.record("oauth_grant", "installation:demo")
    grant.payload = {**grant.payload, "expires_at": time.time() - 1}
    token = AsyncMock(side_effect=OAuthError("oauth_invalid_grant"))
    monkeypatch.setattr(service.http, "token", token)
    assert (await service.status(row.id, "demo"))["status"] == "connected"
    token.assert_not_awaited()
    with pytest.raises(OAuthError, match="oauth_invalid_grant"):
        await service.bearer(row.id, "demo", config)
    await service.db.commit()
    assert (await service.status(row.id, "demo"))["status"] == "expired"
    assert token.await_count == 1
    with pytest.raises(OAuthError, match="oauth_invalid_grant"):
        await service.bearer(row.id, "demo", config)
    assert token.await_count == 1
    grant.payload = {**grant.payload, "invalid_grant": False, "refresh_token": None}
    assert (await service.status(row.id, "demo"))["status"] == "expired"


@pytest.mark.parametrize("action", ["enable", "update"])
async def test_failed_activation_keeps_rotated_refresh_grant(oauth, monkeypatch, action):
    import copy
    from unittest.mock import AsyncMock

    from src.application.services.plugin_marketplace_v3 import (
        MarketplaceV3Error,
        PluginMarketplaceV3,
    )
    from src.infrastructure.plugins.marketplace_snapshot_cache import preflight_expiry

    oauth_service, fixture, row, config = oauth
    callback = await consent(oauth_service, fixture)
    await oauth_service.callback(callback["state"][0], callback["code"][0])
    grant = await oauth_service.record("oauth_grant", "installation:demo")
    original_refresh = grant.payload["refresh_token"]
    grant.payload = {**grant.payload, "expires_at": time.time() - 1}
    package = copy.deepcopy(row.payload["package"])
    package["resources"].update(
        {"skills": [], "apps": {"demo": {"mcp_server": "demo", "resource_uri": "ui://missing"}}}
    )
    package["descriptor"] = {
        "id": "plugin",
        "source_id": "curated",
        "version": "2.0.0",
        "compatible": True,
        "permissions": [],
        "capabilities": ["mcp", "apps"],
    }
    row.payload = {
        **row.payload,
        "plugin_id": "plugin",
        "source_id": "curated",
        "name": "Fixture",
        "capabilities": ["mcp", "apps"],
        "owned_skills": [],
        "owned_servers": [],
        "package": package,
        "status": "enabled" if action == "update" else "downloaded",
    }
    await oauth_service.db.commit()
    runtime = SimpleNamespace(
        create_server=AsyncMock(return_value=SimpleNamespace(id="owned", runtime_status="running")),
        update_server=AsyncMock(return_value=SimpleNamespace(runtime_status="stopped")),
        delete_server=AsyncMock(),
    )
    service = PluginMarketplaceV3(oauth_service.db, "tenant", "project")
    service.mcp = SimpleNamespace(
        runtime_service=runtime,
        tool_cache=SimpleNamespace(invalidate=lambda tenant: None),
        app_service=SimpleNamespace(list_apps=AsyncMock(return_value=[])),
    )
    monkeypatch.setattr(service, "source", AsyncMock(return_value={"trusted": True}))
    data = {"idempotency_key": "failed-activation"}
    if action == "update":
        preview = await service.add_record(
            "preflight",
            {
                "package": package,
                "expires_at": preflight_expiry(),
            },
        )
        data.update({"preflight_id": preview.id, "approved_permissions": []})
        with pytest.raises(MarketplaceV3Error, match="current version is unchanged"):
            await service.mutate(row.id, action, data)
    else:
        result = await service.mutate(row.id, action, data)
        assert result["status"] == "failed"
    await oauth_service.db.commit()
    oauth_service.db.expire_all()
    restarted = MarketplaceOAuth(oauth_service.db, "tenant", "project")
    rotated = await restarted.record("oauth_grant", "installation:demo")
    assert rotated.payload["refresh_token"] != original_refresh
    rotated.payload = {**rotated.payload, "expires_at": time.time() - 1}
    await oauth_service.db.commit()
    # The provider consumed the original refresh token. This second rotation only succeeds
    # when the first rotated grant survived the later failed resource activation.
    assert (await restarted.bearer("installation", "demo", config)).startswith("Bearer ")


async def test_reauthorization_pending_state_wins_over_previous_invalid_grant(oauth):
    service, fixture, row, _ = oauth
    callback = await consent(service, fixture)
    await service.callback(callback["state"][0], callback["code"][0])
    grant = await service.record("oauth_grant", "installation:demo")
    grant.payload = {**grant.payload, "invalid_grant": True, "expires_at": time.time() - 1}
    assert (await service.status(row.id, "demo"))["status"] == "expired"
    callback = await consent(service, fixture, key="reauthorize")
    assert (await service.status(row.id, "demo"))["status"] == "authorizing"
    await service.callback(callback["state"][0], callback["code"][0])
    assert (await service.status(row.id, "demo"))["status"] == "connected"
