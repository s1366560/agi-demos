"""Autonomy attention declarations must reach the sole Workspace Core authority."""

from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI

from src.configuration.workspace_core import WorkspaceCoreSettings
from src.infrastructure.adapters.primary.web import workspace_core_routes
from src.infrastructure.adapters.primary.web.dependencies import get_current_user
from src.infrastructure.plugins.v2.builtin_workspace_core_http_routes import (
    workspace_core_route_definitions_v2,
)
from src.infrastructure.plugins.v2.http_routes import install_route_definitions_v2
from src.infrastructure.workspace_core.client import WorkspaceCoreClient


@pytest.mark.unit
@pytest.mark.parametrize(
    ("method", "suffix"), [("GET", ""), ("POST", "/a1/retry"), ("POST", "/a1/resolve")]
)
@pytest.mark.parametrize("upstream_status", [200, 403])
async def test_attention_routes_proxy_auth_and_revision_without_local_authority(
    monkeypatch: pytest.MonkeyPatch, method: str, suffix: str, upstream_status: int
) -> None:
    path = "/api/v1/workspaces/w1/autonomy/attentions" + suffix
    calls = []

    async def upstream(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        assert request.url.path == path
        assert request.method == method
        assert request.headers["x-memstack-user-id"] == "user-1"
        assert request.headers["x-memstack-user-is-superuser"] == "false"
        assert request.headers["x-memstack-workspace-id"] == "w1"
        assert request.headers["x-memstack-user-authorization"] == "Bearer user-test-token"
        assert request.headers["authorization"] == "Bearer internal-test-token"
        if suffix.endswith("/resolve"):
            assert request.headers["if-match"] == "7"
            assert request.headers["idempotency-key"] == "attention-resolution-test-key"
        return httpx.Response(upstream_status, json={"upstream": True})

    core = WorkspaceCoreClient(
        WorkspaceCoreSettings.model_validate(
            {
                "WORKSPACE_CORE_BASE_URL": "http://workspace-core.test",
                "WORKSPACE_CORE_SERVICE_TOKEN": "internal-test-token",
                "WORKSPACE_CORE_PROVIDER_WEBHOOK_TOKEN": "webhook-test-token",
                "WORKSPACE_CORE_PROVIDER_EVENT_TOKEN": "event-test-token",
                "WORKSPACE_CORE_AGENT_REGISTRY_TOKEN": "registry-test-token",
            }
        ),
        transport=httpx.MockTransport(upstream),
    )
    monkeypatch.setattr(
        workspace_core_routes, "workspace_core_client_v2_from_request", lambda _: core
    )
    app = FastAPI()
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        id="user-1", email="user@example.test", is_superuser=False
    )
    install_route_definitions_v2(app, workspace_core_route_definitions_v2())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://gateway.test"
    ) as client:
        response = await client.request(
            method,
            path,
            headers={
                "Authorization": "Bearer user-test-token",
                "If-Match": "7",
                "Idempotency-Key": "attention-resolution-test-key",
            },
        )
    assert response.status_code == upstream_status
    assert response.json() == {"upstream": True}
    assert calls == [path]
