"""Real HTTP protocol checks for the loopback acceptance service."""

# Standalone stdlib unittest suite; no pytest dependency is required.
# ruff: noqa: PT009

import base64
import hashlib
import http.client
import json
import re
import threading
import unittest
from http.server import ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlencode, urlsplit

from server import Fixture, handler


class OAuthFixtureTest(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = Fixture("http://127.0.0.1:0")
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), handler(self.fixture))
        self.fixture.origin = f"http://127.0.0.1:{self.server.server_port}"
        self.fixture.resource = self.fixture.origin + "/mcp"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def request(
        self,
        path: str,
        data: dict[str, Any] | None = None,
        token: str | None = None,
        form: bool = False,
    ) -> tuple[int, dict[str, str], Any]:
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port)
        headers = {}
        if token:
            headers["Authorization"] = "Bearer " + token
        if data is not None:
            headers["Content-Type"] = (
                "application/x-www-form-urlencoded" if form else "application/json"
            )
        connection.request(
            "GET" if data is None else "POST",
            path,
            None if data is None else urlencode(data) if form else json.dumps(data),
            headers,
        )
        result = connection.getresponse()
        body = result.read().decode()
        response = (
            result.status,
            dict(result.getheaders()),
            json.loads(body) if result.getheader("Content-Type") == "application/json" else body,
        )
        connection.close()
        return response

    def authorize(
        self, client: str = "marketplace-fixture", decision: str = "allow"
    ) -> dict[str, Any]:
        verifier = "a" * 64
        redirect = "http://127.0.0.1:54321/callback"
        query = {
            "client_id": client,
            "redirect_uri": redirect,
            "response_type": "code",
            "state": "opaque-state",
            "resource": self.fixture.resource,
            "scope": "mcp:tools",
            "code_challenge_method": "S256",
            "code_challenge": base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
            .decode()
            .rstrip("="),
        }
        status, page_headers, page = self.request("/authorize?" + urlencode(query))
        self.assertEqual(status, 200)
        self.assertEqual(
            page_headers["Content-Security-Policy"],
            "default-src 'none'; form-action 'self' http://127.0.0.1:54321; frame-ancestors 'none'",
        )
        ticket = re.search(r'name="ticket" value="([^"]+)"', page)[1]
        status, headers, _ = self.request(
            "/consent",
            {
                "ticket": ticket,
                "username": "fixture-user",
                "password": "fixture-password",
                "decision": decision,
            },
            form=True,
        )
        self.assertEqual(status, 302)
        callback = parse_qs(urlsplit(headers["Location"]).query)
        self.assertEqual(callback["state"], ["opaque-state"])
        if decision == "deny":
            return callback
        return {
            "grant_type": "authorization_code",
            "client_id": client,
            "redirect_uri": redirect,
            "resource": self.fixture.resource,
            "code": callback["code"][0],
            "code_verifier": verifier,
        }

    def test_authorization_echo_app_expiry_refresh_rotation_and_revocation(self) -> None:
        status, _, metadata = self.request("/.well-known/oauth-protected-resource/mcp")
        self.assertEqual(status, 200)
        self.assertEqual(metadata["resource"], self.fixture.resource)
        status, _, _ = self.request("/mcp", {"id": 1, "method": "tools/list"})
        self.assertEqual(status, 401)
        grant = self.authorize()
        status, _, tokens = self.request("/token", grant, form=True)
        self.assertEqual(status, 200)
        status, _, echo = self.request(
            "/mcp",
            {
                "id": 2,
                "method": "tools/call",
                "params": {"name": "echo", "arguments": {"text": "OAUTH_ECHO_OK"}},
            },
            tokens["access_token"],
        )
        self.assertEqual(echo["result"]["content"][0]["text"], "OAUTH_ECHO_OK")
        status, _, app = self.request(
            "/mcp",
            {"id": 3, "method": "resources/read", "params": {"uri": "ui://oauth-fixture/app.html"}},
            tokens["access_token"],
        )
        self.assertIn("OAuth connected", app["result"]["contents"][0]["text"])
        self.assertEqual(self.request("/token", grant, form=True)[0], 400)
        self.fixture.tokens[tokens["access_token"]]["expires"] = 0
        self.assertEqual(
            self.request("/mcp", {"id": 4, "method": "tools/list"}, tokens["access_token"])[0], 401
        )
        refresh = {
            "grant_type": "refresh_token",
            "client_id": "marketplace-fixture",
            "resource": self.fixture.resource,
            "refresh_token": tokens["refresh_token"],
        }
        status, _, new = self.request("/token", refresh, form=True)
        self.assertEqual(status, 200)
        self.assertNotEqual(new["refresh_token"], tokens["refresh_token"])
        self.assertEqual(self.request("/token", refresh, form=True)[0], 400)
        self.request("/revoke", {"token": new["access_token"]}, form=True)
        self.assertEqual(
            self.request("/mcp", {"id": 5, "method": "tools/list"}, new["access_token"])[0], 401
        )

    def test_invalid_verifier_resource_client_expired_code_and_denied_consent(self) -> None:
        for change in (
            {"code_verifier": "b" * 64},
            {"resource": self.fixture.origin + "/other"},
            {"client_id": "wrong-client"},
        ):
            grant = self.authorize()
            self.assertEqual(self.request("/token", {**grant, **change}, form=True)[0], 400)
        grant = self.authorize()
        self.fixture.codes[grant["code"]]["expires"] = 0
        self.assertEqual(self.request("/token", grant, form=True)[0], 400)
        self.assertEqual(self.authorize(decision="deny")["error"], ["access_denied"])

    def test_dynamic_registration_binds_redirect(self) -> None:
        status, _, client = self.request(
            "/register",
            {
                "redirect_uris": ["http://127.0.0.1:54321/callback"],
                "token_endpoint_auth_method": "none",
            },
        )
        self.assertEqual(status, 201)
        self.assertEqual(
            self.request("/token", self.authorize(client["client_id"]), form=True)[0], 200
        )
        self.assertFalse(
            self.fixture.redirect_allowed(client["client_id"], "http://127.0.0.1:54322/callback")
        )
        self.assertEqual(
            self.request("/register", {"redirect_uris": ["https://external.example/callback"]})[0],
            400,
        )


if __name__ == "__main__":
    unittest.main()
