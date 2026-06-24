"""Tests for sandbox HTTP service preview proxy helpers."""

from __future__ import annotations

import base64
import json
import logging
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock

import pytest
from fastapi import WebSocketDisconnect
from starlette.datastructures import Headers, QueryParams
from starlette.requests import HTTPConnection, Request
from starlette.responses import Response

from src.infrastructure.adapters.primary.web.dependencies import auth_dependencies
from src.infrastructure.adapters.primary.web.routers import project_sandbox


class _FakeWebSocket:
    def __init__(self) -> None:
        self.headers = Headers()
        self.sent_json: list[object] = []
        self.accepted_subprotocol: str | None = None
        self.close_calls: list[tuple[int | None, str | None]] = []

    async def accept(self, subprotocol: str | None = None) -> None:
        self.accepted_subprotocol = subprotocol

    async def send_json(self, payload: object) -> None:
        self.sent_json.append(payload)

    async def close(self, code: int | None = None, reason: str | None = None) -> None:
        self.close_calls.append((code, reason))


def test_http_service_proxy_rewrites_html_js_css_urls() -> None:
    content = b"""
    <html>
      <link href="/assets/app.css">
      <script src="/assets/app.js"></script>
      <form action="/submit"></form>
      <style>.logo{background:url('/assets/logo.svg')}</style>
      <script>
        fetch("/api/data");
        new EventSource("/events");
        new WebSocket("/hmr");
      </script>
    </html>
    """

    rewritten = project_sandbox._rewrite_http_service_content(
        content,
        "text/html; charset=utf-8",
        "project-1",
        "frontend",
        "token-1",
    ).decode()

    assert (
        "/api/v1/projects/project-1/sandbox/http-services/frontend/proxy/assets/app.css"
        in rewritten
    )
    assert (
        "/api/v1/projects/project-1/sandbox/http-services/frontend/proxy/assets/app.js" in rewritten
    )
    assert "/api/v1/projects/project-1/sandbox/http-services/frontend/proxy/submit" in rewritten
    assert (
        "/api/v1/projects/project-1/sandbox/http-services/frontend/proxy/assets/logo.svg"
        in rewritten
    )
    assert "/api/v1/projects/project-1/sandbox/http-services/frontend/proxy/api/data" in rewritten
    assert "/api/v1/projects/project-1/sandbox/http-services/frontend/proxy/events" in rewritten
    assert (
        "/api/v1/projects/project-1/sandbox/http-services/frontend/proxy/ws/hmr?token=token-1"
        in rewritten
    )


def test_http_service_proxy_rewrites_without_token_for_cookie_auth() -> None:
    rewritten = project_sandbox._rewrite_http_service_content(
        b'<link href="/app.css"><script src="/app.js"></script><script>new WebSocket("/hmr")</script>',
        "text/html",
        "project-1",
        "frontend",
        "",
    ).decode()

    assert "/api/v1/projects/project-1/sandbox/http-services/frontend/proxy/app.css" in rewritten
    assert "/api/v1/projects/project-1/sandbox/http-services/frontend/proxy/app.js" in rewritten
    assert "/api/v1/projects/project-1/sandbox/http-services/frontend/proxy/ws/hmr" in rewritten
    assert "token=" not in rewritten


def test_http_service_proxy_rewrites_redirect_location() -> None:
    rewritten = project_sandbox._rewrite_http_service_location(
        "http://172.18.0.3:3000/login?next=%2F",
        project_id="project-1",
        service_id="frontend",
        token_param="token-1",
        upstream_base_url="http://172.18.0.3:3000/",
    )

    assert rewritten == (
        "/api/v1/projects/project-1/sandbox/http-services/frontend/proxy/login"
        "?next=%2F&token=token-1"
    )


def test_proxy_cookie_seed_token_uses_authorization_header() -> None:
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/proxy",
            "query_string": b"",
            "headers": [(b"authorization", b"Bearer ms_sk_header_token")],
        }
    )

    assert project_sandbox._proxy_cookie_seed_token(request) == "ms_sk_header_token"


def test_proxy_cookie_seed_token_prefers_query_token() -> None:
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/proxy",
            "query_string": b"token=ms_sk_query_token",
            "headers": [(b"authorization", b"Bearer ms_sk_header_token")],
        }
    )

    assert project_sandbox._proxy_cookie_seed_token(request) == "ms_sk_query_token"


async def test_proxy_auth_dependency_accepts_sandbox_proxy_cookie() -> None:
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/proxy",
            "query_string": b"",
            "headers": [(b"cookie", b"sandbox_proxy_token=ms_sk_cookie_token")],
        }
    )

    token = await auth_dependencies.get_api_key_from_header_query_or_cookie(
        request, authorization=None, token=None
    )

    assert token == "ms_sk_cookie_token"


async def test_proxy_auth_dependency_keeps_legacy_desktop_cookie_fallback() -> None:
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/proxy",
            "query_string": b"",
            "headers": [(b"cookie", b"desktop_token=ms_sk_legacy_cookie")],
        }
    )

    token = await auth_dependencies.get_api_key_from_header_query_or_cookie(
        request, authorization=None, token=None
    )

    assert token == "ms_sk_legacy_cookie"


async def test_proxy_auth_dependency_accepts_websocket_subprotocol_token() -> None:
    connection = cast(
        HTTPConnection,
        SimpleNamespace(
            headers=Headers(raw=[(b"sec-websocket-protocol", b"binary, ms_sk_ws_cookie_token")]),
            query_params=QueryParams(""),
            cookies={},
        ),
    )

    token = await auth_dependencies.get_api_key_from_header_query_or_cookie(
        connection, authorization=None, token=None
    )

    assert token == "ms_sk_ws_cookie_token"


async def test_project_terminal_websocket_disconnect_log_omits_session_id(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    session = SimpleNamespace(
        session_id="session-secret",
        container_id="sandbox-1",
        cols=80,
        rows=24,
        is_active=False,
    )
    proxy = SimpleNamespace(create_session=AsyncMock(return_value=session))
    websocket = _FakeWebSocket()
    service = SimpleNamespace(
        get_project_sandbox=AsyncMock(
            return_value=SimpleNamespace(sandbox_id="sandbox-1", terminal_url="ws://terminal")
        )
    )

    async def noop_output_loop(*_args: object) -> None:
        return None

    monkeypatch.setattr(
        project_sandbox,
        "_verify_project_access_or_close",
        AsyncMock(return_value=True),
    )
    monkeypatch.setattr(project_sandbox, "_read_terminal_output_loop", noop_output_loop)
    monkeypatch.setattr(
        project_sandbox,
        "_handle_terminal_input",
        AsyncMock(side_effect=WebSocketDisconnect()),
    )
    monkeypatch.setattr(
        "src.infrastructure.adapters.secondary.sandbox.terminal_proxy.get_terminal_proxy",
        lambda: proxy,
    )
    caplog.set_level(
        logging.INFO,
        logger="src.infrastructure.adapters.primary.web.routers.project_sandbox",
    )

    await project_sandbox.proxy_project_terminal_websocket(
        websocket=cast("project_sandbox.WebSocket", websocket),
        project_id="project-1",
        session_id=None,
        current_user=cast("project_sandbox.User", SimpleNamespace(id="user-1")),
        db=cast("project_sandbox.AsyncSession", SimpleNamespace()),
        service=cast("project_sandbox.ProjectSandboxLifecycleService", service),
    )

    assert websocket.accepted_subprotocol is None
    assert websocket.sent_json == [
        {
            "type": "connected",
            "session_id": "session-secret",
            "cols": 80,
            "rows": 24,
        }
    ]
    assert websocket.close_calls == [(None, None)]
    assert "WebSocket disconnected" in caplog.text
    assert "has_session_id=True" in caplog.text
    assert "session-secret" not in caplog.text


def test_sandbox_proxy_auth_cookie_is_scoped_to_project_sandbox_path() -> None:
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "scheme": "https",
            "server": ("example.test", 443),
            "path": "/api/v1/projects/project-1/sandbox/proxy-auth-cookie",
            "query_string": b"",
            "headers": [],
        }
    )
    response = Response()

    project_sandbox._set_sandbox_proxy_auth_cookie(
        response,
        request,
        "project-1",
        "ms_sk_cookie_token",
    )

    set_cookie = response.headers["set-cookie"]
    assert "sandbox_proxy_token=ms_sk_cookie_token" in set_cookie
    assert "HttpOnly" in set_cookie
    assert "SameSite=strict" in set_cookie
    assert "Secure" in set_cookie
    assert "Path=/api/v1/projects/project-1/sandbox" in set_cookie


def test_sandbox_exec_target_url_rewrites_bridge_ip_to_loopback() -> None:
    rewritten = project_sandbox._sandbox_exec_target_url(
        "http://172.17.0.3:43121/assets/app.js?v=1"
    )

    assert rewritten == "http://127.0.0.1:43121/assets/app.js?v=1"


def test_decode_sandbox_exec_http_response() -> None:
    output = json.dumps(
        {
            "status": 201,
            "headers": {"Content-Type": "text/html"},
            "body_b64": base64.b64encode(b"<h1>ok</h1>").decode("ascii"),
        }
    ).encode("utf-8")

    status, headers, body = project_sandbox._decode_sandbox_exec_http_response(output)

    assert status == 201
    assert headers["content-type"] == "text/html"
    assert body == b"<h1>ok</h1>"
