"""Tests for RFC 8414 OAuth Authorization Server Metadata discovery (P2-21)."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from src.infrastructure.agent.mcp import oauth_discovery
from src.infrastructure.agent.mcp.oauth_discovery import (
    AuthorizationServerMetadata,
    discover_authorization_server_metadata,
    select_token_endpoint_auth_method,
)


def _client_with_handler(handler: Any) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.fixture(autouse=True)
def _isolated_cache() -> None:
    oauth_discovery._clear_cache_for_tests()


@pytest.mark.unit
async def test_rfc8414_happy_path_returns_parsed_metadata() -> None:
    body = {
        "issuer": "https://auth.example.com",
        "authorization_endpoint": "https://auth.example.com/authorize",
        "token_endpoint": "https://auth.example.com/token",
        "registration_endpoint": "https://auth.example.com/register",
        "token_endpoint_auth_methods_supported": [
            "client_secret_basic",
            "client_secret_post",
        ],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/.well-known/oauth-authorization-server"
        return httpx.Response(200, json=body)

    async with _client_with_handler(handler) as client:
        metadata = await discover_authorization_server_metadata(
            "https://auth.example.com/api/mcp", http_client=client
        )

    assert metadata is not None
    assert metadata.issuer == "https://auth.example.com"
    assert metadata.token_endpoint == "https://auth.example.com/token"
    assert metadata.token_endpoint_auth_methods_supported == (
        "client_secret_basic",
        "client_secret_post",
    )


@pytest.mark.unit
async def test_falls_back_to_oidc_when_rfc8414_missing() -> None:
    body = {"issuer": "https://idp.example.com"}
    paths_seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths_seen.append(request.url.path)
        if request.url.path == "/.well-known/oauth-authorization-server":
            return httpx.Response(404)
        return httpx.Response(200, json=body)

    async with _client_with_handler(handler) as client:
        metadata = await discover_authorization_server_metadata(
            "https://idp.example.com", http_client=client
        )

    assert metadata is not None
    assert metadata.issuer == "https://idp.example.com"
    assert paths_seen == [
        "/.well-known/oauth-authorization-server",
        "/.well-known/openid-configuration",
    ]


@pytest.mark.unit
async def test_returns_none_when_neither_endpoint_responds() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    async with _client_with_handler(handler) as client:
        metadata = await discover_authorization_server_metadata(
            "https://blank.example.com", http_client=client
        )

    assert metadata is None


@pytest.mark.unit
async def test_invalid_json_treated_as_missing() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"not-json")

    async with _client_with_handler(handler) as client:
        metadata = await discover_authorization_server_metadata(
            "https://broken.example.com", http_client=client
        )

    assert metadata is None


@pytest.mark.unit
async def test_top_level_non_dict_payload_treated_as_missing() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=json.dumps([1, 2]).encode("utf-8"))

    async with _client_with_handler(handler) as client:
        metadata = await discover_authorization_server_metadata(
            "https://array.example.com", http_client=client
        )

    assert metadata is None


@pytest.mark.unit
async def test_cache_avoids_repeat_fetches() -> None:
    body = {"issuer": "https://cached.example.com"}
    counter = {"hits": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        counter["hits"] += 1
        return httpx.Response(200, json=body)

    async with _client_with_handler(handler) as client:
        first = await discover_authorization_server_metadata(
            "https://cached.example.com/x", http_client=client
        )
        second = await discover_authorization_server_metadata(
            "https://cached.example.com/y", http_client=client
        )

    assert first is second  # same cached instance
    assert counter["hits"] == 1


@pytest.mark.unit
async def test_cache_records_negative_results() -> None:
    counter = {"hits": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        counter["hits"] += 1
        return httpx.Response(404)

    async with _client_with_handler(handler) as client:
        first = await discover_authorization_server_metadata(
            "https://nope.example.com", http_client=client
        )
        second = await discover_authorization_server_metadata(
            "https://nope.example.com", http_client=client
        )

    assert first is None and second is None
    # Two requests on the first call (RFC 8414 + OIDC fallback) and zero on
    # the second (cache hit).
    assert counter["hits"] == 2


@pytest.mark.unit
async def test_invalid_url_returns_none() -> None:
    metadata = await discover_authorization_server_metadata("not-a-url")
    assert metadata is None


@pytest.mark.unit
def test_select_method_prefers_basic_when_secret_present() -> None:
    metadata = AuthorizationServerMetadata(
        issuer="https://x",
        authorization_endpoint=None,
        token_endpoint=None,
        registration_endpoint=None,
        token_endpoint_auth_methods_supported=(
            "client_secret_post",
            "client_secret_basic",
        ),
        raw={},
    )
    assert select_token_endpoint_auth_method(metadata, has_secret=True) == "client_secret_basic"


@pytest.mark.unit
def test_select_method_falls_back_to_post_when_basic_unsupported() -> None:
    metadata = AuthorizationServerMetadata(
        issuer="https://x",
        authorization_endpoint=None,
        token_endpoint=None,
        registration_endpoint=None,
        token_endpoint_auth_methods_supported=("client_secret_post",),
        raw={},
    )
    assert select_token_endpoint_auth_method(metadata, has_secret=True) == "client_secret_post"


@pytest.mark.unit
def test_select_method_uses_none_for_public_client() -> None:
    metadata = AuthorizationServerMetadata(
        issuer="https://x",
        authorization_endpoint=None,
        token_endpoint=None,
        registration_endpoint=None,
        token_endpoint_auth_methods_supported=("none", "client_secret_basic"),
        raw={},
    )
    assert select_token_endpoint_auth_method(metadata, has_secret=False) == "none"


@pytest.mark.unit
def test_select_method_legacy_fallback_when_metadata_missing() -> None:
    assert select_token_endpoint_auth_method(None, has_secret=True) == "client_secret_post"
    assert select_token_endpoint_auth_method(None, has_secret=False) == "none"


@pytest.mark.unit
def test_select_method_legacy_fallback_when_no_overlap() -> None:
    metadata = AuthorizationServerMetadata(
        issuer="https://x",
        authorization_endpoint=None,
        token_endpoint=None,
        registration_endpoint=None,
        token_endpoint_auth_methods_supported=("private_key_jwt",),
        raw={},
    )
    assert select_token_endpoint_auth_method(metadata, has_secret=True) == "client_secret_post"


@pytest.mark.unit
async def test_provider_client_metadata_uses_discovered_method(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """End-to-end: provider.discover() updates client_metadata auth method."""
    from src.infrastructure.agent.mcp.oauth import MCPAuthStorage, MCPOAuthProvider

    storage = MCPAuthStorage(data_dir=tmp_path)
    provider = MCPOAuthProvider(
        mcp_name="x",
        server_url="https://discover.example.com",
        storage=storage,
        client_secret="s3cret",
    )

    # Default (pre-discovery) keeps the legacy hard-coded method.
    assert provider.client_metadata["token_endpoint_auth_method"] == "client_secret_post"

    # Inject discovered metadata advertising basic.
    fake_meta = AuthorizationServerMetadata(
        issuer="https://discover.example.com",
        authorization_endpoint=None,
        token_endpoint=None,
        registration_endpoint=None,
        token_endpoint_auth_methods_supported=("client_secret_basic",),
        raw={},
    )

    async def fake_discover(server_url: str, **_: Any) -> AuthorizationServerMetadata:
        assert server_url == "https://discover.example.com"
        return fake_meta

    monkeypatch.setattr(
        "src.infrastructure.agent.mcp.oauth.discover_authorization_server_metadata",
        fake_discover,
    )

    result = await provider.discover()
    assert result is fake_meta
    assert provider.client_metadata["token_endpoint_auth_method"] == "client_secret_basic"


@pytest.mark.unit
async def test_provider_discover_handles_no_metadata(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src.infrastructure.agent.mcp.oauth import MCPAuthStorage, MCPOAuthProvider

    storage = MCPAuthStorage(data_dir=tmp_path)
    provider = MCPOAuthProvider(
        mcp_name="x",
        server_url="https://no-discovery.example.com",
        storage=storage,
    )

    async def fake_discover(server_url: str, **_: Any) -> None:
        return None

    monkeypatch.setattr(
        "src.infrastructure.agent.mcp.oauth.discover_authorization_server_metadata",
        fake_discover,
    )

    assert await provider.discover() is None
    # No secret + no metadata → legacy "none".
    assert provider.client_metadata["token_endpoint_auth_method"] == "none"


@pytest.mark.unit
async def test_uses_tls_verify_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """When no explicit client is passed, MCP_TLS_VERIFY is honoured."""
    monkeypatch.setenv("MCP_TLS_VERIFY", "false")

    captured: dict[str, Any] = {}

    real_async_client = httpx.AsyncClient

    class _SpyClient(real_async_client):  # type: ignore[misc, valid-type]
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            captured.update(kwargs)
            super().__init__(*args, **kwargs)

        async def get(self, *args: Any, **kwargs: Any) -> httpx.Response:
            return httpx.Response(404)

    monkeypatch.setattr(httpx, "AsyncClient", _SpyClient)

    metadata = await discover_authorization_server_metadata("https://untrusted.example.com")
    assert metadata is None
    assert captured.get("verify") is False
