"""Retirement tests for the plugin protocol V1 control-plane transport."""

from __future__ import annotations

import pytest
from fastapi import FastAPI, status
from fastapi.testclient import TestClient

from src.infrastructure.adapters.primary.web.dependencies import get_current_user
from src.infrastructure.adapters.primary.web.routers import platform_plugins
from src.infrastructure.adapters.secondary.persistence.models import User


def make_client() -> TestClient:
    app = FastAPI()
    app.include_router(platform_plugins.router)
    app.dependency_overrides[get_current_user] = lambda: User(
        id="platform-plugin-user",
        email="platform-plugin@example.com",
        hashed_password="hashed",
        full_name="Platform Plugin User",
        is_active=True,
        is_superuser=False,
    )
    return TestClient(app, raise_server_exceptions=False, follow_redirects=False)


@pytest.mark.unit
@pytest.mark.parametrize(
    ("method", "path", "payload"),
    [
        ("GET", "/api/v1/platform-plugins", None),
        ("GET", "/api/v1/platform-plugins/snapshot", None),
        ("GET", "/api/v1/platform-plugins/shadow-rollout", None),
        ("GET", "/api/v1/platform-plugins/cutover/readiness", None),
        ("POST", "/api/v1/platform-plugins/cutover/approve", {"valid_for_seconds": 3_600}),
        ("POST", "/api/v1/platform-plugins/cutover/revoke", {"reason": "retired"}),
        ("GET", "/api/v1/platform-plugins/http-routes", None),
        (
            "PUT",
            "/api/v1/platform-plugins/http-routes/example-plugin",
            {
                "method": "GET",
                "path": "/api/v1/plugins/{tenant_id}/example",
                "permission": "plugin.example.read",
                "authorization_mode": "tenant_member",
                "enabled": True,
            },
        ),
        ("POST", "/api/v1/platform-plugins/http-routes/reconcile", None),
        ("POST", "/api/v1/platform-plugins/publish", None),
        (
            "POST",
            "/api/v1/platform-plugins/data-plane-state",
            {
                "data_plane_id": "desktop-local",
                "snapshot_digest": "a" * 64,
                "requested_version": 1,
                "applied_version": 1,
                "status": "ack",
            },
        ),
        ("DELETE", "/api/v1/platform-plugins/packages/example", None),
    ],
)
def test_authenticated_v1_control_plane_routes_return_stable_410(
    method: str,
    path: str,
    payload: dict[str, object] | None,
) -> None:
    response = make_client().request(method, path, json=payload)

    assert response.status_code == status.HTTP_410_GONE
    assert response.json()["detail"] == {
        "code": "plugin_protocol_v1_retired",
        "message": "Plugin protocol V1 is retired; use the V2 plugin control plane",
        "migration_target": "/api/v1/plugin-marketplace",
    }


@pytest.mark.unit
def test_v2_route_is_not_captured_by_v1_retirement_fallback() -> None:
    response = make_client().get("/api/v1/platform-plugins/v2/distribution")

    assert response.status_code != status.HTTP_410_GONE


@pytest.mark.unit
def test_unknown_v2_route_is_not_captured_by_v1_retirement_fallback() -> None:
    response = make_client().get("/api/v1/platform-plugins/v2/unknown")

    assert response.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.unit
def test_v1_retirement_fallback_rejects_unlisted_legacy_paths() -> None:
    response = make_client().patch(
        "/api/v1/platform-plugins/unknown/legacy/path",
        json={"ignored": True},
    )

    assert response.status_code == status.HTTP_410_GONE
    assert response.json()["detail"]["code"] == "plugin_protocol_v1_retired"
