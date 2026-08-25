"""Production V2 ownership tests for the tenant SMTP configuration HTTP row."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.schemas.smtp_schemas import SmtpConfigResponse
from src.configuration.workspace_core import get_workspace_core_settings
from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.domain.model.plugins.runtime import PluginGenerationDescriptorV2
from src.infrastructure.adapters.primary.web.routers import smtp_config as smtp_config_router
from src.infrastructure.adapters.primary.web.smtp_config_application_authority_v2 import (
    SmtpConfigApplicationAuthorityV2,
    smtp_config_application_authority_dependency_v2,
)
from src.infrastructure.adapters.primary.web.startup.generation_http_v2 import (
    mount_generation_http_dispatcher_v2,
)
from src.infrastructure.adapters.secondary.persistence.models import User as DBUser
from src.infrastructure.plugins.v2 import builtin_smtp_config_http_routes as subject
from src.infrastructure.plugins.v2.boundary import pin_operation_context_v2
from src.infrastructure.plugins.v2.builtin_http_routes import build_builtin_route_graph_v2
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.http_routes import RouteTableRegistryV2
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2
from src.infrastructure.plugins.v2.smtp_config_services import SmtpConfigApplicationServicesV2


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
def test_smtp_config_row_registers_production_handlers_without_forwarding_wrappers() -> None:
    definitions = subject.smtp_config_route_definitions_v2()

    assert tuple(definition.endpoint for definition in definitions) == (
        smtp_config_router.get_smtp_config,
        smtp_config_router.upsert_smtp_config,
        smtp_config_router.delete_smtp_config,
        smtp_config_router.test_smtp_config,
    )
    assert not hasattr(subject, "get_smtp_config_v2")
    assert not hasattr(subject, "upsert_smtp_config_v2")
    assert not hasattr(subject, "delete_smtp_config_v2")
    assert not hasattr(subject, "test_smtp_config_v2")


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
            () if definition.methods == ("WEBSOCKET",) else tuple(sorted(definition.methods)),
        )
        for definition in claimed.table.definitions
    )
    assert claimed.table.openapi_snapshot(descriptor).schema["openapi"].startswith("3.")
    assert claimed.v2_owned_row_ids == ("smtp-config",)


@pytest.mark.unit
async def test_generation_dispatcher_executes_smtp_config_v2_before_static_fallback() -> None:
    user = SimpleNamespace(id="user-1", is_superuser=True)
    db = object()
    calls: list[tuple[object, ...]] = []
    fallback_calls: list[str] = []
    response = _smtp_response()

    class SmtpService:
        async def get_config(self, tenant_id: str) -> SimpleNamespace:
            calls.append(("get", tenant_id))
            return SimpleNamespace(
                id=response.id,
                tenant_id=response.tenant_id,
                smtp_host=response.smtp_host,
                smtp_port=response.smtp_port,
                smtp_username=response.smtp_username,
                smtp_password_encrypted="c2VjcmV0",
                from_email=response.from_email,
                from_name=response.from_name,
                use_tls=response.use_tls,
            )

    authority = SmtpConfigApplicationAuthorityV2(
        operation=cast(Any, SimpleNamespace()),
        db=cast(AsyncSession, db),
        current_user=cast(DBUser, user),
        tenant_id="tenant-1",
        services=SmtpConfigApplicationServicesV2(smtp=cast(Any, SmtpService())),
    )

    async def authority_override() -> SmtpConfigApplicationAuthorityV2:
        calls.append(("authority", authority.tenant_id, authority.current_user, authority.db))
        return authority

    graph = build_builtin_route_graph_v2(
        workspace_core_settings=get_workspace_core_settings(),
        route_definitions=subject.smtp_config_route_definitions_v2(),
        dependency_overrides={
            smtp_config_application_authority_dependency_v2: authority_override,
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
        fallback_calls.append(tenant_id)
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
    assert calls == [
        ("authority", "tenant-1", user, db),
        ("get", "tenant-1"),
    ]
    assert fallback_calls == []
    await host.close()


@pytest.mark.unit
def test_smtp_config_module_definition_uses_generated_contract_binding() -> None:
    definition = subject.builtin_smtp_config_http_routes_definition_v2()

    assert definition.module_ref == subject.SMTP_CONFIG_HTTP_ROUTES_MODULE_V2
    assert definition.contract_digest.startswith("sha256:")
