"""Production V2 ownership tests for the tenant SMTP configuration HTTP row."""

from __future__ import annotations

import httpx
import pytest
from fastapi import FastAPI

from src.application.schemas.smtp_schemas import (
    SmtpConfigCreate,
    SmtpConfigResponse,
    SmtpTestRequest,
)
from src.configuration.workspace_core import get_workspace_core_settings
from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.domain.model.plugins.runtime import PluginGenerationDescriptorV2
from src.infrastructure.adapters.primary.web.startup.generation_http_v2 import (
    mount_generation_http_dispatcher_v2,
)
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.plugins.v2 import builtin_smtp_config_http_routes as subject
from src.infrastructure.plugins.v2.boundary import pin_operation_context_v2
from src.infrastructure.plugins.v2.builtin_http_routes import build_builtin_route_graph_v2
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.http_routes import RouteTableRegistryV2
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2


def _smtp_response() -> SmtpConfigResponse:
    return SmtpConfigResponse(
        id="smtp-1",
        tenant_id="tenant-1",
        smtp_host="smtp.example.com",
        smtp_port=587,
        smtp_username="mailer",
        smtp_password_masked="****ret",
        from_email="mailer@example.com",
        from_name="MemStack",
        use_tls=True,
    )


def _smtp_create() -> SmtpConfigCreate:
    return SmtpConfigCreate(
        smtp_host="smtp.example.com",
        smtp_port=587,
        smtp_username="mailer",
        smtp_password="operation-secret",
        from_email="mailer@example.com",
        from_name="MemStack",
        use_tls=True,
    )


@pytest.mark.unit
def test_smtp_config_row_is_a_complete_explicit_v2_contribution() -> None:
    definitions = subject.smtp_config_route_definitions_v2()

    assert {
        (method, definition.path) for definition in definitions for method in definition.methods
    } == {
        ("GET", "/api/v1/tenants/{tenant_id}/smtp-config"),
        ("PUT", "/api/v1/tenants/{tenant_id}/smtp-config"),
        ("DELETE", "/api/v1/tenants/{tenant_id}/smtp-config"),
        ("POST", "/api/v1/tenants/{tenant_id}/smtp-config/test"),
    }
    assert {definition.owner_entry_id for definition in definitions} == {
        subject.SMTP_CONFIG_HTTP_ROUTES_ENTRY_V2
    }
    assert {definition.replaces_builtin_row_id for definition in definitions} == {"smtp-config"}


@pytest.mark.unit
def test_smtp_config_row_preserves_route_order_and_openapi() -> None:
    descriptor = PluginGenerationDescriptorV2(
        profile_id="smtp-config-route-parity",
        generation=1,
        digest="0" * 64,
    )
    claimed = build_builtin_route_graph_v2(
        workspace_core_settings=get_workspace_core_settings(),
        route_definitions=subject.smtp_config_route_definitions_v2(),
    )

    assert claimed.route_signatures == tuple(
        (
            definition.path,
            definition.name,
            ()
            if definition.methods == ("WEBSOCKET",)
            else tuple(sorted(definition.methods)),
        )
        for definition in claimed.table.definitions
    )
    assert claimed.table.openapi_snapshot(descriptor).schema["openapi"].startswith("3.")
    assert claimed.v2_owned_row_ids == ("smtp-config",)


@pytest.mark.unit
async def test_generation_dispatcher_executes_smtp_config_v2_before_static_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = object()
    db = object()
    calls: list[tuple[str, object, object]] = []
    response = _smtp_response()

    async def get_handler(
        tenant_id: str,
        current_user: object,
        db_value: object,
    ) -> SmtpConfigResponse:
        calls.append((tenant_id, current_user, db_value))
        return response

    async def current_user_override() -> object:
        return user

    async def db_override() -> object:
        return db

    monkeypatch.setattr(subject, "_get_smtp_config", get_handler)
    graph = build_builtin_route_graph_v2(
        workspace_core_settings=get_workspace_core_settings(),
        route_definitions=subject.smtp_config_route_definitions_v2(),
        dependency_overrides={
            subject.get_current_user: current_user_override,
            get_db: db_override,
        },
    )
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    await host.bootstrap(
        profile_path="config/plugin-profiles/memstack-default.v2.yaml",
        manifest_paths=("config/plugin-manifests-v2/memstack-runtime-kernel.v2.json",),
        generation=1,
        version=1,
    )
    distribution = host.current_distribution
    assert distribution is not None
    registry = RouteTableRegistryV2()
    await registry.publish(distribution.descriptor, graph.table)
    outer = FastAPI()
    outer.state.platform_plugin_route_registry_v2 = registry
    mount_generation_http_dispatcher_v2(outer)

    @outer.get("/api/v1/tenants/{tenant_id}/smtp-config")
    async def static_fallback(tenant_id: str) -> dict[str, str]:
        return {"source": "static", "tenant_id": tenant_id}

    async with (
        pin_operation_context_v2(
            host,
            operation_id="smtp-config-route-authority",
            scope=ScopeV2(kind=ScopeKindV2.ROOT),
        ),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=outer),
            base_url="http://test",
        ) as client,
    ):
        result = await client.get("/api/v1/tenants/tenant-1/smtp-config")

    assert result.status_code == 200
    assert result.json() == response.model_dump(mode="json")
    assert calls == [("tenant-1", user, db)]
    await host.close()


@pytest.mark.unit
async def test_smtp_config_v2_handlers_delegate_without_static_router_mount(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = object()
    db = object()
    body = _smtp_create()
    test_body = SmtpTestRequest(recipient_email="recipient@example.com")
    response = _smtp_response()
    calls: list[tuple[str, tuple[object, ...]]] = []

    async def get_handler(*args: object) -> SmtpConfigResponse:
        calls.append(("get", args))
        return response

    async def upsert_handler(*args: object) -> SmtpConfigResponse:
        calls.append(("upsert", args))
        return response

    async def delete_handler(*args: object) -> None:
        calls.append(("delete", args))

    async def test_handler(*args: object) -> dict[str, str]:
        calls.append(("test", args))
        return {"message": "sent"}

    monkeypatch.setattr(subject, "_get_smtp_config", get_handler)
    monkeypatch.setattr(subject, "_upsert_smtp_config", upsert_handler)
    monkeypatch.setattr(subject, "_delete_smtp_config", delete_handler)
    monkeypatch.setattr(subject, "_test_smtp_config", test_handler)

    assert await subject.get_smtp_config_v2("tenant-1", user, db) == response
    assert await subject.upsert_smtp_config_v2("tenant-1", body, user, db) == response
    assert await subject.delete_smtp_config_v2("tenant-1", user, db) is None
    assert await subject.test_smtp_config_v2("tenant-1", test_body, user, db) == {"message": "sent"}
    assert calls == [
        ("get", ("tenant-1", user, db)),
        ("upsert", ("tenant-1", body, user, db)),
        ("delete", ("tenant-1", user, db)),
        ("test", ("tenant-1", test_body, user, db)),
    ]


@pytest.mark.unit
def test_smtp_config_module_definition_uses_generated_contract_binding() -> None:
    definition = subject.builtin_smtp_config_http_routes_definition_v2()

    assert definition.module_ref == subject.SMTP_CONFIG_HTTP_ROUTES_MODULE_V2
    assert definition.contract_digest.startswith("sha256:")
