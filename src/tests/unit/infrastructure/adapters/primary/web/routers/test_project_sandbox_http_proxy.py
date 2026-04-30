"""Tests for sandbox HTTP service preview proxy helpers."""

from __future__ import annotations

import base64
import json

from starlette.requests import Request

from src.infrastructure.adapters.primary.web.routers import project_sandbox


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
