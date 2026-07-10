"""Tests for sandbox MCP WebSocket platform authentication."""

import asyncio
from types import SimpleNamespace
from typing import Any

from src.server.websocket_server import AuthConfig, MCPWebSocketServer


def test_auth_config_defaults_fail_closed() -> None:
    config = AuthConfig()

    assert config.enabled is True
    assert config.allow_localhost is False


def test_static_token_is_required_for_remote_clients() -> None:
    asyncio.run(_assert_static_token_is_required_for_remote_clients())


async def _assert_static_token_is_required_for_remote_clients() -> None:
    server = MCPWebSocketServer(
        auth_config=AuthConfig(static_token="sandbox-capability"),
    )

    missing = SimpleNamespace(remote="10.0.0.8", query_string="", headers={})
    accepted, auth_info, error = await server._authenticate_request(missing)
    assert accepted is False
    assert auth_info is None
    assert error == "Authentication required: no token provided"

    valid = SimpleNamespace(
        remote="10.0.0.8",
        query_string="",
        headers={"Authorization": "Bearer sandbox-capability"},
    )
    accepted, auth_info, error = await server._authenticate_request(valid)
    assert accepted is True
    assert auth_info == {"mode": "static_token"}
    assert error is None


class _FakeValidationResponse:
    status = 200

    async def __aenter__(self) -> "_FakeValidationResponse":
        return self

    async def __aexit__(self, *args: Any) -> None:
        return None

    async def json(self) -> dict[str, Any]:
        return {
            "valid": True,
            "project_id": "project-1",
            "user_id": None,
            "sandbox_type": "local",
        }


class _FakeClientSession:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def post(self, url: str, **kwargs: Any) -> _FakeValidationResponse:
        self.calls.append({"url": url, **kwargs})
        return _FakeValidationResponse()


def test_platform_validation_sends_service_bearer_token() -> None:
    asyncio.run(_assert_platform_validation_sends_service_bearer_token())


async def _assert_platform_validation_sends_service_bearer_token() -> None:
    server = MCPWebSocketServer(
        auth_config=AuthConfig(
            enabled=True,
            platform_url="http://platform",
            platform_service_token="service-secret",
        )
    )
    fake_session = _FakeClientSession()
    server._http_session = fake_session

    result = await server._validate_platform_token("sandbox-token")

    assert result == {
        "mode": "platform_token",
        "project_id": "project-1",
        "user_id": None,
        "sandbox_type": "local",
    }
    assert fake_session.calls[0]["url"] == "http://platform/api/v1/sandbox/token/validate"
    assert fake_session.calls[0]["json"] == {"token": "sandbox-token"}
    assert fake_session.calls[0]["headers"] == {"Authorization": "Bearer service-secret"}
