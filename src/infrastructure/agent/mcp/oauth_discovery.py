"""RFC 8414 OAuth 2.0 Authorization Server Metadata discovery.

Fetches the well-known metadata document for an OAuth 2.0 Authorization
Server (RFC 8414) with a fallback to the OpenID Connect Discovery
document (``/.well-known/openid-configuration``). Results are cached
per-issuer with a 1 hour TTL.

Used by :mod:`src.infrastructure.agent.mcp.oauth` to decide
``token_endpoint_auth_method`` based on the server's actually-supported
authentication methods (P2-21).
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse, urlunparse

import httpx

from src.infrastructure.mcp._security import tls_verify_default

logger = logging.getLogger(__name__)

# RFC 8414 well-known suffix.
_RFC8414_PATH = "/.well-known/oauth-authorization-server"

# OpenID Connect Discovery 1.0 well-known suffix (fallback).
_OIDC_PATH = "/.well-known/openid-configuration"

# Discovery HTTP timeout. Auth servers should respond well under this; if
# they do not we degrade gracefully to ``None`` and the caller falls back
# to its hard-coded defaults.
_DISCOVERY_TIMEOUT_SECONDS: float = 10.0

# Cache TTL. Auth-server metadata changes rarely; an hour is plenty.
_CACHE_TTL_SECONDS: float = 3600.0

# Auth methods we know how to implement, in our preferred order. RFC 6749
# §2.3.1 recommends ``client_secret_basic`` when a secret is available,
# falling back to ``client_secret_post`` and finally ``none`` for public
# clients.
_PREFERRED_AUTH_METHODS_WITH_SECRET: tuple[str, ...] = (
    "client_secret_basic",
    "client_secret_post",
)
_PREFERRED_AUTH_METHODS_NO_SECRET: tuple[str, ...] = ("none",)


@dataclass(frozen=True)
class AuthorizationServerMetadata:
    """Subset of RFC 8414 metadata fields we care about."""

    issuer: str
    authorization_endpoint: str | None
    token_endpoint: str | None
    registration_endpoint: str | None
    token_endpoint_auth_methods_supported: tuple[str, ...]
    raw: dict[str, Any]


@dataclass
class _CacheEntry:
    metadata: AuthorizationServerMetadata | None
    expires_at: float


# Process-local cache keyed on the normalised issuer URL. Holds negative
# results too so we don't hammer servers that lack discovery endpoints.
_cache: dict[str, _CacheEntry] = {}
_cache_lock = asyncio.Lock()


def _issuer_root(server_url: str) -> str:
    """Return the issuer root for a server URL (scheme + netloc, no path)."""
    parsed = urlparse(server_url)
    if not parsed.scheme or not parsed.netloc:
        raise ValueError(f"Invalid server URL: {server_url!r}")
    return urlunparse((parsed.scheme, parsed.netloc, "", "", "", ""))


def _parse_metadata(payload: dict[str, Any]) -> AuthorizationServerMetadata | None:
    issuer = payload.get("issuer")
    if not isinstance(issuer, str):
        return None
    methods_raw = payload.get("token_endpoint_auth_methods_supported", [])
    if isinstance(methods_raw, list):
        methods = tuple(m for m in methods_raw if isinstance(m, str))
    else:
        methods = ()
    return AuthorizationServerMetadata(
        issuer=issuer,
        authorization_endpoint=_str_or_none(payload.get("authorization_endpoint")),
        token_endpoint=_str_or_none(payload.get("token_endpoint")),
        registration_endpoint=_str_or_none(payload.get("registration_endpoint")),
        token_endpoint_auth_methods_supported=methods,
        raw=payload,
    )


def _str_or_none(value: object) -> str | None:
    return value if isinstance(value, str) else None


async def _fetch_one(client: httpx.AsyncClient, url: str) -> AuthorizationServerMetadata | None:
    try:
        response = await client.get(url)
    except httpx.HTTPError as exc:
        logger.debug("OAuth metadata fetch failed for %s: %s", url, exc)
        return None
    if response.status_code != 200:
        logger.debug("OAuth metadata fetch returned %s for %s", response.status_code, url)
        return None
    try:
        payload = response.json()
    except ValueError as exc:
        logger.warning("OAuth metadata at %s is not valid JSON: %s", url, exc)
        return None
    if not isinstance(payload, dict):
        return None
    return _parse_metadata(payload)


async def discover_authorization_server_metadata(
    server_url: str,
    *,
    http_client: httpx.AsyncClient | None = None,
    cache: dict[str, _CacheEntry] | None = None,
) -> AuthorizationServerMetadata | None:
    """Discover RFC 8414 metadata for ``server_url``, falling back to OIDC.

    Args:
        server_url: Any URL on the authorization server. Only ``scheme``
            and ``netloc`` are used; the path is discarded.
        http_client: Optional ``httpx.AsyncClient`` to use. When omitted, a
            short-lived client honouring ``MCP_TLS_VERIFY`` is constructed.
        cache: Optional cache override (used by tests).

    Returns:
        Parsed metadata, or ``None`` when neither well-known document is
        available. ``None`` results are also cached so that we do not
        repeatedly probe a server that has no metadata.
    """
    bucket = cache if cache is not None else _cache
    try:
        issuer = _issuer_root(server_url)
    except ValueError:
        return None

    now = time.monotonic()
    async with _cache_lock:
        entry = bucket.get(issuer)
        if entry is not None and entry.expires_at > now:
            return entry.metadata

    owns_client = http_client is None
    client = http_client or httpx.AsyncClient(
        timeout=_DISCOVERY_TIMEOUT_SECONDS,
        verify=tls_verify_default(),
    )
    try:
        metadata = await _fetch_one(client, issuer + _RFC8414_PATH)
        if metadata is None:
            metadata = await _fetch_one(client, issuer + _OIDC_PATH)
    finally:
        if owns_client:
            await client.aclose()

    async with _cache_lock:
        bucket[issuer] = _CacheEntry(
            metadata=metadata,
            expires_at=time.monotonic() + _CACHE_TTL_SECONDS,
        )
    return metadata


def select_token_endpoint_auth_method(
    metadata: AuthorizationServerMetadata | None,
    *,
    has_secret: bool,
) -> str:
    """Select the ``token_endpoint_auth_method`` for client registration.

    Falls back to the legacy hard-coded behaviour
    (``client_secret_post`` if we have a secret, ``none`` otherwise) when
    metadata is unavailable or advertises no overlap with our supported
    methods. RFC 6749 §2.3.1 prefers HTTP Basic when a secret is present.
    """
    legacy = "client_secret_post" if has_secret else "none"
    if metadata is None:
        return legacy
    supported = metadata.token_endpoint_auth_methods_supported
    if not supported:
        return legacy
    preferred = (
        _PREFERRED_AUTH_METHODS_WITH_SECRET if has_secret else _PREFERRED_AUTH_METHODS_NO_SECRET
    )
    for method in preferred:
        if method in supported:
            return method
    return legacy


def _clear_cache_for_tests() -> None:
    """Clear the module cache. For unit tests only."""
    _cache.clear()


__all__ = (
    "AuthorizationServerMetadata",
    "_clear_cache_for_tests",
    "discover_authorization_server_metadata",
    "select_token_endpoint_auth_method",
)
