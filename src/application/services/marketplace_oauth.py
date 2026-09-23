"""Scope-bound MCP OAuth grants and one-use challenges in encrypted marketplace records."""

from __future__ import annotations

import copy
import hashlib
import json
import secrets
import time
from typing import Any, cast
from urllib.parse import urlencode
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.adapters.secondary.persistence.plugin_marketplace_models_v3 import (
    MarketplaceRecordV3,
)
from src.infrastructure.plugins.marketplace_credentials import (
    configure_transport,
    open_transport,
    seal,
)
from src.infrastructure.plugins.marketplace_oauth_protocol import (
    OAuthError,
    OAuthHTTP,
    canonical_resource,
    oauth_config,
    pkce_challenge,
)


def oauth_service_views(payload: dict[str, Any]) -> list[dict[str, Any]]:
    servers = payload.get("package", {}).get("resources", {}).get("mcp_servers", {})
    saved = payload.get("oauth_status", {})
    return [
        {"name": name, **saved.get(name, {"status": "not_connected"})}
        for name, server in servers.items()
        if oauth_config(server) is not None
    ]


class MarketplaceOAuth:
    def __init__(
        self,
        db: AsyncSession,
        tenant_id: str,
        project_id: str = "",
        *,
        http: OAuthHTTP | None = None,
    ) -> None:
        super().__init__()
        self.db, self.tenant_id, self.project_id = db, tenant_id, project_id or ""
        self.http = http or OAuthHTTP()

    async def record(
        self, kind: str, key: str, *, lock: bool = False
    ) -> MarketplaceRecordV3 | None:
        query = select(MarketplaceRecordV3).where(
            MarketplaceRecordV3.tenant_id == self.tenant_id,
            MarketplaceRecordV3.project_id == self.project_id,
            MarketplaceRecordV3.kind == kind,
            MarketplaceRecordV3.record_key == key,
        )
        if lock:
            query = query.with_for_update().execution_options(populate_existing=True)
        return await self.db.scalar(query)

    async def installation(
        self, installation_id: str, *, lock: bool = False
    ) -> MarketplaceRecordV3:
        query = select(MarketplaceRecordV3).where(
            MarketplaceRecordV3.id == installation_id,
            MarketplaceRecordV3.kind == "installation",
            MarketplaceRecordV3.tenant_id == self.tenant_id,
            MarketplaceRecordV3.project_id == self.project_id,
        )
        if lock:
            query = query.with_for_update().execution_options(populate_existing=True)
        row = await self.db.scalar(query)
        if row is None or row.payload["status"] == "uninstalled":
            raise OAuthError("oauth_installation_unavailable")
        return row

    async def put(self, kind: str, key: str, payload: dict[str, Any]) -> MarketplaceRecordV3:
        row = await self.record(kind, key, lock=True)
        if row is None:
            row = MarketplaceRecordV3(
                id=str(uuid4()),
                tenant_id=self.tenant_id,
                project_id=self.project_id,
                kind=kind,
                record_key=key,
                payload=payload,
            )
            self.db.add(row)
        else:
            row.payload = payload
        await self.db.flush()
        return row

    @staticmethod
    def server(row: MarketplaceRecordV3, name: str) -> tuple[dict[str, Any], dict[str, Any]]:
        config = row.payload["package"]["resources"]["mcp_servers"].get(name)
        auth = oauth_config(config or {})
        if not config or auth is None or "url" not in config:
            raise OAuthError("oauth_service_not_available")
        if config.get("type", "http") != "http" or "command" in config:
            raise OAuthError("oauth_requires_streamable_http")
        return config, auth

    def update_status(
        self, row: MarketplaceRecordV3, name: str, status: str, reason: str | None = None
    ) -> dict[str, Any]:
        view = {"status": status, **({"reason": reason} if reason else {})}
        row.payload = {
            **row.payload,
            "oauth_status": {**row.payload.get("oauth_status", {}), name: view},
        }
        return view

    async def status(self, installation_id: str, name: str) -> dict[str, Any]:
        row = await self.installation(installation_id)
        _ = self.server(row, name)
        current = row.payload.get("oauth_status", {}).get(name, {})
        if current.get("status") == "authorizing":
            challenges = await self.db.scalars(
                select(MarketplaceRecordV3).where(
                    MarketplaceRecordV3.tenant_id == self.tenant_id,
                    MarketplaceRecordV3.project_id == self.project_id,
                    MarketplaceRecordV3.kind == "oauth_challenge",
                )
            )
            if any(
                challenge.payload.get("installation_id") == installation_id
                and challenge.payload.get("server") == name
                and not challenge.payload.get("consumed")
                and challenge.payload.get("expires_at", 0) > time.time()
                for challenge in challenges
            ):
                return current
            self.update_status(row, name, "expired", "oauth_challenge_expired")
        grant = await self.record("oauth_grant", f"{installation_id}:{name}")
        if grant:
            expired = grant.payload.get("expires_at", 0) <= time.time()
            usable = not grant.payload.get("invalid_grant") and (
                not expired or bool(grant.payload.get("refresh_token"))
            )
            return {
                **self.update_status(
                    row,
                    name,
                    "connected" if usable else "expired",
                ),
                "expires_at": grant.payload.get("expires_at"),
            }
        return row.payload.get("oauth_status", {}).get(name, {"status": "not_connected"})

    async def start(
        self,
        installation_id: str,
        name: str,
        user_id: str,
        redirect_uri: str,
        key: str,
        options: dict[str, Any],
    ) -> dict[str, Any]:
        row = await self.installation(installation_id, lock=True)
        config, auth = self.server(row, name)
        if row.payload["status"] == "enabled":
            raise OAuthError("disable_plugin_before_reauthorization")
        request_hash = hashlib.sha256(
            repr((installation_id, name, user_id, redirect_uri, sorted(options.items()))).encode()
        ).hexdigest()
        existing = await self.record("oauth_request", key)
        if existing:
            if existing.payload["request_hash"] != request_hash:
                raise OAuthError("oauth_idempotency_conflict")
            return existing.payload["response"]
        previous = await self.db.scalars(
            select(MarketplaceRecordV3).where(
                MarketplaceRecordV3.tenant_id == self.tenant_id,
                MarketplaceRecordV3.project_id == self.project_id,
                MarketplaceRecordV3.kind == "oauth_challenge",
            )
        )
        for challenge in previous:
            if (
                challenge.payload.get("installation_id") == installation_id
                and challenge.payload.get("server") == name
            ):
                challenge.payload = {
                    k: v
                    for k, v in {**challenge.payload, "consumed": True}.items()
                    if k not in {"verifier", "client"}
                }
        try:
            auth = open_transport(configure_transport(auth, row.payload.get("configuration", {})))
            metadata = await self.http.discover(config["url"])
            client = await self.http.client(
                metadata, {**auth, **{k: v for k, v in options.items() if v}}, redirect_uri
            )
            scopes = metadata.get("required_scopes") or auth.get("scopes", [])
            if not isinstance(scopes, list):
                raise OAuthError("oauth_scopes_invalid")
            values = cast("list[object]", scopes)
            if any(not isinstance(scope, str) for scope in values):
                raise OAuthError("oauth_scopes_invalid")
            scopes = cast("list[str]", values)
            nonce, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(48)
            challenge_id = str(uuid4())
            state = f"{challenge_id}.{nonce}"
            expires_at = time.time() + 600
            challenge = MarketplaceRecordV3(
                id=challenge_id,
                tenant_id=self.tenant_id,
                project_id=self.project_id,
                kind="oauth_challenge",
                record_key=challenge_id,
                payload={
                    "installation_id": installation_id,
                    "server": name,
                    "user_id": user_id,
                    "version": row.payload["version"],
                    "digest": row.payload["package"]["digest"],
                    "state_hash": hashlib.sha256(state.encode()).hexdigest(),
                    "verifier": seal(verifier),
                    "metadata": metadata,
                    "client": seal(json.dumps(client)),
                    "redirect_uri": redirect_uri,
                    "expires_at": expires_at,
                    "consumed": False,
                    "scopes": scopes,
                },
            )
            self.db.add(challenge)
            parameters = {
                "response_type": "code",
                "client_id": client["client_id"],
                "redirect_uri": redirect_uri,
                "state": state,
                "code_challenge": pkce_challenge(verifier),
                "code_challenge_method": "S256",
                "resource": metadata["resource"],
                "scope": " ".join(scopes),
            }
            url = (
                metadata["authorization_endpoint"]
                + ("&" if "?" in metadata["authorization_endpoint"] else "?")
                + urlencode(parameters)
            )
            response = {
                **self.update_status(row, name, "authorizing"),
                "authorization_url": url,
                "expires_at": expires_at,
            }
        except ValueError as exc:
            response = self.update_status(row, name, "needs_configuration", str(exc))
        _ = await self.put(
            "oauth_request",
            key,
            {
                "installation_id": installation_id,
                "request_hash": request_hash,
                "response": response,
            },
        )
        return response

    async def callback(
        self, state: str, code: str | None, error: str | None = None
    ) -> dict[str, Any]:
        challenge_id = state.partition(".")[0]
        challenge = await self.record("oauth_challenge", challenge_id)
        if challenge is None or not secrets.compare_digest(
            challenge.payload["state_hash"], hashlib.sha256(state.encode()).hexdigest()
        ):
            raise OAuthError("oauth_state_invalid")
        # All mutations lock installation before challenge/grant to prevent callback/cancel deadlocks.
        row = await self.installation(challenge.payload["installation_id"], lock=True)
        challenge = await self.record("oauth_challenge", challenge_id, lock=True)
        if challenge is None:
            raise OAuthError("oauth_state_invalid")
        saved = challenge.payload
        if saved.get("consumed") or saved["expires_at"] <= time.time():
            raise OAuthError("oauth_challenge_expired_or_used")
        challenge.payload = {
            k: v for k, v in {**saved, "consumed": True}.items() if k not in {"verifier", "client"}
        }
        if (
            row.payload["version"] != saved["version"]
            or row.payload["package"]["digest"] != saved["digest"]
        ):
            raise OAuthError("oauth_installation_version_changed")
        current, _ = self.server(row, saved["server"])
        if canonical_resource(current["url"]) != saved["metadata"]["resource"]:
            raise OAuthError("oauth_installation_resource_changed")
        if row.payload["status"] == "enabled":
            raise OAuthError("oauth_installation_state_changed")
        if error or not code:
            return self.update_status(row, saved["server"], "error", "oauth_authorization_denied")
        client = json.loads(open_transport(saved["client"]))
        try:
            token = await self.http.token(
                saved["metadata"]["token_endpoint"],
                {
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": saved["redirect_uri"],
                    "code_verifier": open_transport(saved["verifier"]),
                    "resource": saved["metadata"]["resource"],
                    **client,
                },
            )
            granted = token.get("scope", " ".join(saved["scopes"])).split()
            if not set(granted).issubset(saved["scopes"]):
                raise OAuthError("oauth_unapproved_scopes")
            _ = await self.put(
                "oauth_grant",
                f"{row.id}:{saved['server']}",
                {
                    "installation_id": row.id,
                    "server": saved["server"],
                    "metadata": saved["metadata"],
                    "client": saved["client"],
                    "access_token": seal(token["access_token"]),
                    "refresh_token": seal(token["refresh_token"])
                    if token.get("refresh_token")
                    else None,
                    "expires_at": time.time() + token.get("expires_in", 3600),
                    "scopes": granted,
                },
            )
            return self.update_status(row, saved["server"], "connected")
        except OAuthError as exc:
            return self.update_status(row, saved["server"], "error", str(exc))
        finally:
            challenge.payload = {
                k: v for k, v in challenge.payload.items() if k not in {"verifier", "client"}
            }

    async def bearer(
        self,
        installation_id: str,
        name: str,
        config: dict[str, Any],
        *,
        require_enabled: bool = False,
    ) -> str:
        row = await self.installation(installation_id, lock=True)
        current, _ = self.server(row, name)
        if require_enabled and row.payload["status"] != "enabled":
            raise OAuthError("oauth_installation_not_enabled")
        if require_enabled and (
            canonical_resource(current["url"]) != canonical_resource(config["url"])
            or oauth_config(current) != oauth_config(config)
        ):
            raise OAuthError("oauth_installation_changed")
        grant = await self.record("oauth_grant", f"{installation_id}:{name}", lock=True)
        if grant is None:
            raise OAuthError("oauth_authorization_required")
        saved = grant.payload
        if saved.get("invalid_grant"):
            raise OAuthError("oauth_invalid_grant")
        auth = oauth_config(config) or {}
        if canonical_resource(config["url"]) != saved["metadata"]["resource"] or not set(
            auth.get("scopes", [])
        ).issubset(saved["scopes"]):
            raise OAuthError("oauth_reauthorization_required")
        if saved["expires_at"] <= time.time() + 5:
            if not saved.get("refresh_token"):
                raise OAuthError("oauth_authorization_expired")
            client = json.loads(open_transport(saved["client"]))
            try:
                token = await self.http.token(
                    saved["metadata"]["token_endpoint"],
                    {
                        "grant_type": "refresh_token",
                        "refresh_token": open_transport(saved["refresh_token"]),
                        "resource": saved["metadata"]["resource"],
                        **client,
                    },
                )
            except OAuthError as exc:
                if str(exc) == "oauth_invalid_grant":
                    grant.payload = {**saved, "invalid_grant": True}
                    self.update_status(row, name, "expired", "oauth_invalid_grant")
                    await self.db.flush()
                raise
            if not set(token.get("scope", " ".join(saved["scopes"])).split()).issubset(
                saved["scopes"]
            ):
                raise OAuthError("oauth_unapproved_scopes")
            grant.payload = {
                **saved,
                "access_token": seal(token["access_token"]),
                "refresh_token": seal(token["refresh_token"])
                if token.get("refresh_token")
                else saved["refresh_token"],
                "expires_at": time.time() + token.get("expires_in", 3600),
            }
        return "Bearer " + open_transport(grant.payload["access_token"])

    async def control(
        self, installation_id: str, name: str, action: str, key: str
    ) -> dict[str, Any]:
        _ = await self.installation(installation_id, lock=True)
        request_hash = hashlib.sha256(
            json.dumps([installation_id, name, action]).encode()
        ).hexdigest()
        previous = await self.record("oauth_request", key)
        if previous:
            if previous.payload["request_hash"] != request_hash:
                raise OAuthError("oauth_idempotency_conflict")
            return previous.payload["response"]
        response = await self.disconnect(installation_id, name, cancel_only=action == "cancel")
        _ = await self.put(
            "oauth_request",
            key,
            {
                "installation_id": installation_id,
                "request_hash": request_hash,
                "response": response,
            },
        )
        return response

    async def disconnect(
        self, installation_id: str, name: str, *, cancel_only: bool = False
    ) -> dict[str, Any]:
        row = await self.installation(installation_id, lock=True)
        _ = self.server(row, name)
        if not cancel_only and row.payload["status"] == "enabled":
            raise OAuthError("disable_plugin_before_disconnecting")
        challenges = await self.db.scalars(
            select(MarketplaceRecordV3).where(
                MarketplaceRecordV3.tenant_id == self.tenant_id,
                MarketplaceRecordV3.project_id == self.project_id,
                MarketplaceRecordV3.kind == "oauth_challenge",
            )
        )
        for challenge in challenges:
            if (
                challenge.payload.get("installation_id") == installation_id
                and challenge.payload.get("server") == name
            ):
                challenge.payload = {
                    k: v
                    for k, v in {**challenge.payload, "consumed": True}.items()
                    if k not in {"verifier", "client"}
                }
        if not cancel_only:
            grant = await self.record("oauth_grant", f"{installation_id}:{name}", lock=True)
            if grant:
                endpoint = grant.payload["metadata"].get("revocation_endpoint")
                if endpoint:
                    client = json.loads(open_transport(grant.payload["client"]))
                    _ = await self.http.request(
                        "POST",
                        endpoint,
                        {
                            "token": open_transport(
                                grant.payload.get("refresh_token") or grant.payload["access_token"]
                            ),
                            **client,
                        },
                        form=True,
                    )
                await self.db.delete(grant)
        return self.update_status(row, name, "not_connected")


async def authorize_transports(
    service: Any,  # noqa: ANN401
    payload: dict[str, Any],
    servers: dict[str, Any],
) -> dict[str, Any]:
    """Inject sealed authorization only at the existing sandbox credential boundary."""
    oauth = MarketplaceOAuth(service.db, service.tenant_id, service.project_id)
    result = copy.deepcopy(servers)
    for name, config in result.items():
        if oauth_config(config) is not None:
            bearer = await oauth.bearer(payload.get("oauth_owner", payload["id"]), name, config)
            config["headers"] = {**config.get("headers", {}), "Authorization": seal(bearer)}
            config.pop("oauth", None)
            config.pop("auth", None)
    return result
