"""Loopback-only OAuth + protected MCP acceptance fixture; never deploy publicly."""

import argparse
import base64
import hashlib
import html
import json
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlencode, urlsplit


class Fixture:
    def __init__(self, origin: str, token_ttl: int = 30) -> None:
        self.origin = origin
        self.resource = origin + "/mcp"
        self.token_ttl = token_ttl
        self.clients = {"marketplace-fixture": {"redirect_uris": None}}
        self.pending = {}
        self.codes = {}
        self.tokens = {}
        self.refresh = {}
        self.lock = threading.RLock()

    def redirect_allowed(self, client: str | None, redirect: str) -> bool:
        parsed = urlsplit(redirect)
        if parsed.fragment or parsed.username or parsed.password:
            return False
        registered = self.clients.get(client)
        if registered is None:
            return False
        if registered["redirect_uris"] is not None:
            return redirect in registered["redirect_uris"]
        return (
            parsed.scheme == "http"
            and parsed.hostname in ("127.0.0.1", "localhost")
            and parsed.path.endswith("/callback")
        )

    def issue(self, grant: dict[str, Any]) -> dict[str, Any]:
        access, refresh = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        self.tokens[access] = {**grant, "expires": time.time() + self.token_ttl}
        self.refresh[refresh] = {**grant, "expires": time.time() + 600}
        return {
            "access_token": access,
            "refresh_token": refresh,
            "token_type": "Bearer",
            "expires_in": self.token_ttl,
            "scope": grant["scope"],
        }


# The factory keeps each standalone HTTP server bound to its own fixture state.
def handler(fixture: Fixture) -> type[BaseHTTPRequestHandler]:  # noqa: C901
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:
            pass  # Never log authorization codes, tokens or callback query strings.

        def send(
            self,
            status: int,
            value: dict[str, Any] | str,
            content_type: str = "application/json",
            headers: dict[str, str] | None = None,
        ) -> None:
            body = (
                json.dumps(value).encode() if content_type == "application/json" else value.encode()
            )
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-Content-Type-Options", "nosniff")
            for key, item in (headers or {}).items():
                self.send_header(key, item)
            self.end_headers()
            self.wfile.write(body)

        def error(self, code: str, status: int = 400) -> None:
            self.send(status, {"error": code})

        def body(self) -> dict[str, Any]:
            size = int(self.headers.get("Content-Length", 0))
            if size > 65536:
                raise ValueError("request_too_large")
            raw = self.rfile.read(size)
            if "application/json" in self.headers.get("Content-Type", ""):
                return json.loads(raw or "{}")
            return {key: values[0] for key, values in parse_qs(raw.decode()).items()}

        # Each protocol endpoint terminates with its own HTTP response.
        def do_GET(self) -> None:  # noqa: PLR0911
            path = urlsplit(self.path).path
            if path.startswith("/.well-known/oauth-protected-resource"):
                return self.send(
                    200,
                    {
                        "resource": fixture.resource,
                        "authorization_servers": [fixture.origin],
                        "scopes_supported": ["mcp:tools"],
                    },
                )
            if path in (
                "/.well-known/oauth-authorization-server",
                "/.well-known/openid-configuration",
            ):
                return self.send(
                    200,
                    {
                        "issuer": fixture.origin,
                        "authorization_endpoint": fixture.origin + "/authorize",
                        "token_endpoint": fixture.origin + "/token",
                        "registration_endpoint": fixture.origin + "/register",
                        "revocation_endpoint": fixture.origin + "/revoke",
                        "response_types_supported": ["code"],
                        "grant_types_supported": ["authorization_code", "refresh_token"],
                        "code_challenge_methods_supported": ["S256"],
                        "token_endpoint_auth_methods_supported": ["none"],
                        "scopes_supported": ["mcp:tools"],
                    },
                )
            if path == "/authorize":
                params = {
                    key: values[0] for key, values in parse_qs(urlsplit(self.path).query).items()
                }
                if (
                    params.get("response_type") != "code"
                    or params.get("code_challenge_method") != "S256"
                    or not params.get("code_challenge")
                    or not params.get("state")
                    or params.get("resource") != fixture.resource
                    or not fixture.redirect_allowed(
                        params.get("client_id"), params.get("redirect_uri", "")
                    )
                ):
                    return self.error("invalid_request")
                if set(params.get("scope", "").split()) - {"mcp:tools"}:
                    return self.error("invalid_scope")
                callback = urlsplit(params["redirect_uri"])
                callback_origin = f"{callback.scheme}://{callback.netloc}"
                ticket = secrets.token_urlsafe(24)
                with fixture.lock:
                    fixture.pending[ticket] = {**params, "expires": time.time() + 120}
                return self.send(
                    200,
                    '<!doctype html><html><head><title>Marketplace OAuth fixture</title></head><body><h1>Connect marketplace fixture</h1><p>Local acceptance service. Sign in as fixture-user with fixture-password.</p><p>Permission: MCP echo tools and app resources.</p><form method="post" action="/consent"><input type="hidden" name="ticket" value="'
                    + html.escape(ticket)
                    + '"><label>Username <input name="username" autocomplete="username"></label><label>Password <input name="password" type="password" autocomplete="current-password"></label><button name="decision" value="allow">Authorize</button><button name="decision" value="deny">Deny</button></form></body></html>',
                    "text/html",
                    {
                        "Content-Security-Policy": f"default-src 'none'; form-action 'self' {callback_origin}; frame-ancestors 'none'"
                    },
                )
            if path == "/health":
                return self.send(200, {"status": "ready"})
            if path == "/mcp":
                token = self.headers.get("Authorization", "").removeprefix("Bearer ")
                grant = fixture.tokens.get(token)
                if not grant or grant["expires"] < time.time():
                    return self.send(
                        401,
                        {"error": "invalid_token"},
                        headers={
                            "WWW-Authenticate": 'Bearer resource_metadata="'
                            + fixture.origin
                            + '/.well-known/oauth-protected-resource/mcp"'
                        },
                    )
                return self.error("method_not_allowed", 405)
            self.error("not_found", 404)

        def do_POST(self) -> None:
            try:
                params = self.body()
                with fixture.lock:
                    self.post(urlsplit(self.path).path, params)
            except (ValueError, KeyError, TypeError):
                self.error("invalid_request")

        # Keep the standalone fixture endpoint dispatch and OAuth error exits explicit.
        def post(self, path: str, params: dict[str, Any]) -> None:  # noqa: C901, PLR0911, PLR0912
            if path == "/register":
                redirects = params.get("redirect_uris", [])
                if (
                    not redirects
                    or not isinstance(redirects, list)
                    or params.get("token_endpoint_auth_method", "none") != "none"
                    or any(
                        not isinstance(uri, str)
                        or urlsplit(uri).scheme != "http"
                        or urlsplit(uri).hostname not in ("localhost", "127.0.0.1")
                        or urlsplit(uri).fragment
                        for uri in redirects
                    )
                ):
                    return self.error("invalid_client_metadata")
                client = "fixture-" + secrets.token_urlsafe(12)
                fixture.clients[client] = {"redirect_uris": redirects}
                return self.send(
                    201,
                    {
                        "client_id": client,
                        "redirect_uris": redirects,
                        "token_endpoint_auth_method": "none",
                        "grant_types": ["authorization_code", "refresh_token"],
                        "response_types": ["code"],
                    },
                )
            if path == "/consent":
                grant = fixture.pending.get(params.get("ticket"))
                if not grant or grant["expires"] < time.time():
                    return self.error("invalid_request")
                if params.get("decision") == "deny":
                    fixture.pending.pop(params["ticket"])
                    return self.send(
                        302,
                        "",
                        "text/plain",
                        {
                            "Location": grant["redirect_uri"]
                            + "?"
                            + urlencode({"error": "access_denied", "state": grant["state"]})
                        },
                    )
                if (
                    params.get("username") != "fixture-user"
                    or params.get("password") != "fixture-password"
                ):
                    return self.error("invalid_credentials", 401)
                fixture.pending.pop(params["ticket"])
                code = secrets.token_urlsafe(24)
                fixture.codes[code] = {**grant, "expires": time.time() + 60}
                return self.send(
                    302,
                    "",
                    "text/plain",
                    {
                        "Location": grant["redirect_uri"]
                        + "?"
                        + urlencode({"code": code, "state": grant["state"]})
                    },
                )
            if path == "/token":
                if params.get("grant_type") == "authorization_code":
                    grant = fixture.codes.pop(params.get("code"), None)
                    verifier = params.get("code_verifier", "")
                    challenge = (
                        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
                        .decode()
                        .rstrip("=")
                    )
                    if (
                        not grant
                        or grant["expires"] < time.time()
                        or not 43 <= len(verifier) <= 128
                        or not secrets.compare_digest(grant["code_challenge"], challenge)
                        or params.get("redirect_uri") != grant["redirect_uri"]
                    ):
                        return self.error("invalid_grant")
                elif params.get("grant_type") == "refresh_token":
                    grant = fixture.refresh.pop(params.get("refresh_token"), None)
                    if not grant or grant["expires"] < time.time():
                        return self.error("invalid_grant")
                else:
                    return self.error("unsupported_grant_type")
                if (
                    params.get("client_id") != grant["client_id"]
                    or params.get("resource") != fixture.resource
                ):
                    return self.error("invalid_grant")
                return self.send(200, fixture.issue(grant))
            if path == "/revoke":
                fixture.tokens.pop(params.get("token"), None)
                fixture.refresh.pop(params.get("token"), None)
                return self.send(200, {})
            if path == "/mcp":
                token = self.headers.get("Authorization", "").removeprefix("Bearer ")
                grant = fixture.tokens.get(token)
                if (
                    not grant
                    or grant["expires"] < time.time()
                    or grant["resource"] != fixture.resource
                ):
                    return self.send(
                        401,
                        {"error": "invalid_token"},
                        headers={
                            "WWW-Authenticate": 'Bearer resource_metadata="'
                            + fixture.origin
                            + '/.well-known/oauth-protected-resource/mcp"'
                        },
                    )
                if "id" not in params:
                    return self.send(202, "")
                method = params.get("method")
                args = params.get("params", {})
                resource = {
                    "uri": "ui://oauth-fixture/app.html",
                    "name": "OAuth fixture app",
                    "mimeType": "text/html;profile=mcp-app",
                }
                results = {
                    "initialize": {
                        "protocolVersion": args.get("protocolVersion", "2024-11-05"),
                        "capabilities": {"tools": {}, "resources": {}},
                        "serverInfo": {"name": "oauth-fixture", "version": "1.0.0"},
                    },
                    "ping": {},
                    "tools/list": {
                        "tools": [
                            {
                                "name": "echo",
                                "description": "Echo after OAuth authorization",
                                "inputSchema": {
                                    "type": "object",
                                    "properties": {"text": {"type": "string"}},
                                    "required": ["text"],
                                },
                                "_meta": {"ui": {"resourceUri": resource["uri"]}},
                            }
                        ]
                    },
                    "resources/list": {"resources": [resource]},
                }
                if method == "tools/call" and args.get("name") == "echo":
                    result = {
                        "content": [
                            {"type": "text", "text": args.get("arguments", {}).get("text", "")}
                        ]
                    }
                elif method == "resources/read" and args.get("uri") == resource["uri"]:
                    result = {
                        "contents": [
                            {
                                **resource,
                                "text": "<!doctype html><html><body><h1>OAuth connected</h1><p>Protected marketplace app is available.</p></body></html>",
                            }
                        ]
                    }
                else:
                    result = results.get(method)
                return self.send(
                    200,
                    {
                        "jsonrpc": "2.0",
                        "id": params["id"],
                        **(
                            {"result": result}
                            if result is not None
                            else {"error": {"code": -32601, "message": "Method not found"}}
                        ),
                    },
                )
            self.error("not_found", 404)

    return Handler


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=18891)
    parser.add_argument("--token-ttl", type=int, default=30)
    options = parser.parse_args()
    fixture = Fixture(f"http://127.0.0.1:{options.port}", options.token_ttl)
    server = ThreadingHTTPServer(("127.0.0.1", options.port), handler(fixture))
    print(f"Local OAuth fixture ready at {fixture.origin}", flush=True)
    server.serve_forever()
