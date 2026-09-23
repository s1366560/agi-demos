"""Bounded MCP OAuth discovery and token requests; never log protocol secrets."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import http.client
import json
import math
import os
import re
import socket
import ssl
from typing import Any, cast
from urllib.parse import urlencode, urlsplit, urlunsplit

from src.infrastructure.plugins.marketplace_sources import (
    _public_address,  # pyright: ignore[reportPrivateUsage]
)


class OAuthError(ValueError):
    """Safe protocol error suitable for a credential-free API response."""


def oauth_config(server: dict[str, Any]) -> dict[str, Any] | None:
    value = server.get("oauth", server.get("auth"))
    if isinstance(value, dict):
        config = cast("dict[str, Any]", value)
        if "oauth" in server or config.get("type") in ("oauth", "oauth2"):
            return config
    return None


def canonical_resource(url: str) -> str:
    parsed = urlsplit(url)
    if (
        parsed.scheme not in {"http", "https"}
        or parsed.username
        or parsed.password
        or parsed.fragment
        or not parsed.hostname
    ):
        raise OAuthError("invalid_resource_url")
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path or "/", parsed.query, ""))


def pkce_challenge(verifier: str) -> str:
    return (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    )


def _request(
    method: str, url: str, data: dict[str, Any] | None, form: bool
) -> tuple[int, dict[str, str], dict[str, Any]]:
    parsed = urlsplit(url)
    origin = urlunsplit((parsed.scheme, parsed.netloc, "", "", ""))
    test_origin = os.environ.get("PLUGIN_MARKETPLACE_OAUTH_TEST_ORIGIN", "")
    local_test = (
        os.environ.get("ENVIRONMENT", "production") in {"development", "test"}
        and test_origin == origin
        and parsed.scheme == "http"
        and parsed.hostname in {"127.0.0.1", "::1"}
        and not parsed.username
        and not parsed.password
        and not parsed.fragment
    )
    if local_test:
        host, port = str(parsed.hostname), parsed.port or 80
        connection = http.client.HTTPConnection(host, port, timeout=15)
        path = parsed.path or "/"
        if parsed.query:
            path += "?" + parsed.query
    else:
        host, port, address, path = _public_address(url)
        connection = http.client.HTTPSConnection(host, port, timeout=15)
        raw = socket.create_connection((address, port), timeout=15)
        try:
            connection.sock = ssl.create_default_context().wrap_socket(raw, server_hostname=host)
        except BaseException:
            raw.close()
            raise
    body = (urlencode(data) if form else json.dumps(data)).encode() if data is not None else None
    headers = {"Accept": "application/json"}
    if body is not None:
        headers["Content-Type"] = (
            "application/x-www-form-urlencoded" if form else "application/json"
        )
    try:
        connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        raw_body = response.read(1024 * 1024 + 1)
        if len(raw_body) > 1024 * 1024:
            raise OAuthError("oauth_response_too_large")
        if 300 <= response.status < 400:
            raise OAuthError("oauth_redirect_not_allowed")
        try:
            payload: Any = json.loads(raw_body) if raw_body else {}
        except (ValueError, UnicodeError):
            payload = {}
        if not isinstance(payload, dict):
            raise OAuthError("invalid_oauth_response")
        return (
            response.status,
            {k.lower(): v for k, v in response.getheaders()},
            cast("dict[str, Any]", payload),
        )
    finally:
        connection.close()


class OAuthHTTP:
    async def request(
        self, method: str, url: str, data: dict[str, Any] | None = None, *, form: bool = False
    ) -> tuple[int, dict[str, str], dict[str, Any]]:
        try:
            return await asyncio.to_thread(_request, method, url, data, form)
        except OAuthError:
            raise
        except Exception as exc:
            raise OAuthError("oauth_endpoint_unavailable") from exc

    async def json(self, url: str) -> dict[str, Any]:
        status, _, payload = await self.request("GET", url)
        if status != 200:
            raise OAuthError("oauth_metadata_unavailable")
        return payload

    async def discover(self, resource: str) -> dict[str, Any]:  # noqa: C901, PLR0912
        resource = canonical_resource(resource)
        _, headers, _ = await self.request("GET", resource)
        challenge = headers.get("www-authenticate", "")
        match = re.search(r'\bresource_metadata="([^"\r\n]+)"', challenge)
        parsed = urlsplit(resource)
        origin = urlunsplit((parsed.scheme, parsed.netloc, "", "", ""))
        urls = (
            [match[1]]
            if match
            else list(
                dict.fromkeys(
                    [
                        origin + "/.well-known/oauth-protected-resource" + parsed.path.rstrip("/"),
                        origin + "/.well-known/oauth-protected-resource",
                    ]
                )
            )
        )
        protected = None
        for url in urls:
            try:
                protected = await self.json(url)
                break
            except OAuthError:
                if match:
                    raise
        if not protected or canonical_resource(protected.get("resource", "")) != resource:
            raise OAuthError("oauth_resource_mismatch")
        issuers = protected.get("authorization_servers")
        if not isinstance(issuers, list) or not issuers or not isinstance(issuers[0], str):
            raise OAuthError("oauth_authorization_server_missing")
        issuer = issuers[0]
        parsed = urlsplit(canonical_resource(issuer))
        origin = urlunsplit((parsed.scheme, parsed.netloc, "", "", ""))
        path = parsed.path.rstrip("/")
        urls = [
            origin + "/.well-known/oauth-authorization-server" + path,
            origin + "/.well-known/openid-configuration" + path,
        ]
        if path:
            urls.append(origin + path + "/.well-known/openid-configuration")
        metadata = None
        for url in urls:
            try:
                metadata = await self.json(url)
                break
            except OAuthError:
                continue
        if not metadata or metadata.get("issuer", "").rstrip("/") != issuer.rstrip("/"):
            raise OAuthError("oauth_issuer_mismatch")
        if "S256" not in metadata.get("code_challenge_methods_supported", []):
            raise OAuthError("oauth_pkce_s256_required")
        for field in ("authorization_endpoint", "token_endpoint"):
            raw_endpoint = metadata.get(field)
            if not isinstance(raw_endpoint, str):
                raise OAuthError("oauth_endpoint_missing")
            _ = canonical_resource(raw_endpoint)
            endpoint = urlsplit(raw_endpoint)
            test_origin = os.environ.get("PLUGIN_MARKETPLACE_OAUTH_TEST_ORIGIN", "")
            local = (
                os.environ.get("ENVIRONMENT") in {"test", "development"}
                and endpoint.hostname in {"127.0.0.1", "::1"}
                and urlunsplit((endpoint.scheme, endpoint.netloc, "", "", "")) == test_origin
            )
            if endpoint.scheme != "https" and not local:
                raise OAuthError("oauth_endpoint_requires_https")
        scope = re.search(r'\bscope="([^"\r\n]*)"', challenge)
        return {
            **metadata,
            "resource": resource,
            "required_scopes": scope[1].split() if scope else protected.get("scopes_supported", []),
        }

    async def client(
        self, metadata: dict[str, Any], config: dict[str, Any], redirect_uri: str
    ) -> dict[str, Any]:
        if config.get("client_id"):
            return {key: config[key] for key in ("client_id", "client_secret") if config.get(key)}
        client_url = config.get("client_metadata_url")
        if client_url and metadata.get("client_id_metadata_document_supported"):
            if not isinstance(client_url, str):
                raise OAuthError("oauth_client_metadata_requires_https")
            if urlsplit(client_url).scheme != "https":
                raise OAuthError("oauth_client_metadata_requires_https")
            document = await self.json(client_url)
            if document.get("client_id") != client_url or redirect_uri not in document.get(
                "redirect_uris", []
            ):
                raise OAuthError("oauth_client_metadata_mismatch")
            return {"client_id": client_url}
        if metadata.get("registration_endpoint"):
            status, _, document = await self.request(
                "POST",
                metadata["registration_endpoint"],
                {
                    "client_name": "MemStack plugin marketplace",
                    "redirect_uris": [redirect_uri],
                    "grant_types": ["authorization_code", "refresh_token"],
                    "response_types": ["code"],
                    "token_endpoint_auth_method": "none",
                },
            )
            if status not in (200, 201) or not isinstance(document.get("client_id"), str):
                raise OAuthError("oauth_client_registration_failed")
            if document.get("token_endpoint_auth_method", "none") not in (
                "none",
                "client_secret_post",
            ):
                raise OAuthError("oauth_client_auth_method_unsupported")
            return {key: document[key] for key in ("client_id", "client_secret") if key in document}
        raise OAuthError("oauth_client_configuration_required")

    async def token(self, endpoint: str, fields: dict[str, Any]) -> dict[str, Any]:
        status, _, token = await self.request("POST", endpoint, fields, form=True)
        if status != 200 and token.get("error") == "invalid_grant":
            raise OAuthError("oauth_invalid_grant")
        if (
            status != 200
            or not isinstance(token.get("access_token"), str)
            or not token["access_token"]
        ):
            raise OAuthError("oauth_token_exchange_failed")
        if str(token.get("token_type", "")).lower() != "bearer":
            raise OAuthError("oauth_bearer_token_required")
        if len(token["access_token"]) > 65536 or any(c in token["access_token"] for c in "\r\n\0"):
            raise OAuthError("oauth_access_token_invalid")
        if "scope" in token and not isinstance(token["scope"], str):
            raise OAuthError("oauth_token_scope_invalid")
        if "refresh_token" in token and (
            not isinstance(token["refresh_token"], str) or not token["refresh_token"]
        ):
            raise OAuthError("oauth_refresh_token_invalid")
        if token.get("resource") not in (None, fields.get("resource")):
            raise OAuthError("oauth_token_resource_mismatch")
        if (
            type(token.get("expires_in", 3600)) not in (int, float)
            or not math.isfinite(token.get("expires_in", 3600))
            or token.get("expires_in", 3600) <= 0
        ):
            raise OAuthError("oauth_token_expiry_invalid")
        return token
