"""Approval-gated plugin HTTP route assembly tests."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import src.infrastructure.adapters.primary.web.startup.http_route_capabilities as module
from src.infrastructure.adapters.primary.web.dependencies import get_current_user
from src.infrastructure.adapters.primary.web.startup.http_route_capabilities import (
    build_http_route_capability_assembler,
    install_http_route_capabilities,
)
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.plugins.http_routes import HttpRouteCapabilityRow


class FakeSession:
    async def __aenter__(self) -> FakeSession:
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None


class FakeRepository:
    def __init__(self, session: object, granted: bool = True) -> None:
        _ = session
        self.granted = granted

    async def list_http_routes(self) -> list[SimpleNamespace]:
        return list(DESIRED_ROWS)

    async def permission_is_granted(
        self,
        *,
        plugin_id: str,
        permission: str,
        scope_type: str,
        scope_id: str,
    ) -> bool:
        assert plugin_id == "example-plugin"
        assert permission == "plugin.example.read"
        assert scope_type == "tenant"
        assert scope_id == "tenant-1"
        return self.granted


DESIRED_ROWS = [
    SimpleNamespace(
        plugin_id="example-plugin",
        method="GET",
        path="/api/v1/plugins/{tenant_id}/example",
        permission="plugin.example.read",
        authorization_mode="tenant_member",
        enabled=True,
    )
]


def _registry_routes() -> dict[str, list[SimpleNamespace]]:
    async def handler(tenant_id: str) -> dict[str, str]:
        return {"tenant_id": tenant_id}

    return {
        "example-plugin": [
            SimpleNamespace(
                method="GET",
                path="/api/v1/plugins/{tenant_id}/example",
                plugin_name="example-plugin",
                handler=handler,
            )
        ]
    }


def _client(app: FastAPI) -> TestClient:
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id="user-1")
    app.dependency_overrides[get_db] = lambda: FakeSession()
    return TestClient(app)


@pytest.mark.unit
def test_plugin_route_v2_mount_enforces_tenant_and_exact_permission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checked: list[tuple[str, str]] = []

    async def fake_require_tenant_access(
        db: object,
        user: object,
        tenant_id: str,
        *,
        require_admin: bool = False,
    ) -> None:
        checked.append((tenant_id, str(require_admin)))

    monkeypatch.setattr(module, "require_tenant_access", fake_require_tenant_access)
    monkeypatch.setattr(module, "PlatformPluginGovernanceRepository", FakeRepository)
    app = FastAPI()
    assembler = build_http_route_capability_assembler(
        app,
        registry_routes=_registry_routes(),
        desired_rows=DESIRED_ROWS,
    )
    rows = [
        HttpRouteCapabilityRow(
            plugin_id="example-plugin",
            method="GET",
            path="/api/v1/plugins/{tenant_id}/example",
            permission="plugin.example.read",
            authorization_mode="tenant_member",
        )
    ]
    handlers = {
        ("GET", "/api/v1/plugins/{tenant_id}/example"): _registry_routes()["example-plugin"][
            0
        ].handler
    }

    assert assembler.reconcile(rows, handlers) == (1, 0)
    response = _client(app).get("/api/v1/plugins/tenant-1/example")

    assert response.status_code == 200
    assert response.json() == {"tenant_id": "tenant-1"}
    assert checked == [("tenant-1", "False")]


@pytest.mark.unit
def test_plugin_route_v2_denies_missing_exact_permission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_require_tenant_access(
        db: object,
        user: object,
        tenant_id: str,
        *,
        require_admin: bool = False,
    ) -> None:
        return None

    class DeniedRepository(FakeRepository):
        async def permission_is_granted(self, **_kwargs: object) -> bool:
            return False

    monkeypatch.setattr(module, "require_tenant_access", fake_require_tenant_access)
    monkeypatch.setattr(module, "PlatformPluginGovernanceRepository", DeniedRepository)
    app = FastAPI()
    assembler = build_http_route_capability_assembler(
        app,
        registry_routes=_registry_routes(),
        desired_rows=DESIRED_ROWS,
    )
    row = HttpRouteCapabilityRow(
        plugin_id="example-plugin",
        method="GET",
        path="/api/v1/plugins/{tenant_id}/example",
        permission="plugin.example.read",
        authorization_mode="tenant_member",
    )
    handler = _registry_routes()["example-plugin"][0].handler
    assert assembler.reconcile([row], {("GET", row.path): handler}) == (1, 0)

    response = _client(app).get("/api/v1/plugins/tenant-1/example")

    assert response.status_code == 403
    assert response.json() == {"detail": "Plugin route permission is required"}


@pytest.mark.unit
def test_plugin_route_v2_requires_scope_path_parameter() -> None:
    app = FastAPI()

    async def handler(tenant_id: str) -> dict[str, str]:
        return {"tenant_id": tenant_id}

    rows = [
        SimpleNamespace(
            plugin_id="example-plugin",
            method="GET",
            path="/api/v1/plugins/example",
            permission="plugin.example.read",
            authorization_mode="tenant_member",
            enabled=True,
        )
    ]
    registry_routes = {
        "example-plugin": [
            SimpleNamespace(
                method="GET",
                path="/api/v1/plugins/example",
                plugin_name="example-plugin",
                handler=handler,
            )
        ]
    }

    with pytest.raises(ValueError, match=r"must expose \{tenant_id\}"):
        build_http_route_capability_assembler(
            app,
            registry_routes=registry_routes,
            desired_rows=rows,
        )


@pytest.mark.unit
async def test_install_plugin_routes_is_v2_only_and_mounts_desired_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "src.configuration.config.get_settings",
        lambda: SimpleNamespace(platform_plugin_http_route_v2=False),
    )
    assert await install_http_route_capabilities(FastAPI(), session_factory=FakeSession) is None

    monkeypatch.setattr(
        "src.configuration.config.get_settings",
        lambda: SimpleNamespace(platform_plugin_http_route_v2=True),
    )
    monkeypatch.setattr(
        module,
        "PlatformPluginGovernanceRepository",
        FakeRepository,
    )
    monkeypatch.setattr(
        "src.infrastructure.agent.plugins.registry.get_plugin_registry",
        lambda: SimpleNamespace(list_http_routes=_registry_routes),
    )
    monkeypatch.setattr(module, "require_tenant_access", fake_noop_tenant_access)
    app = FastAPI()
    assembler = await install_http_route_capabilities(app, session_factory=FakeSession)

    assert assembler is not None
    assert len(assembler._mounted) == 1
    assembler.dispose()
    assert assembler._mounted == {}


async def fake_noop_tenant_access(
    db: object,
    user: object,
    tenant_id: str,
    *,
    require_admin: bool = False,
) -> None:
    return None
