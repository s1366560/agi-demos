"""Production V2 ownership tests for the tenants HTTP row."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from src.application.schemas.tenant import TenantCreate, TenantUpdate
from src.configuration.workspace_core import get_workspace_core_settings
from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.domain.model.plugins.runtime import PluginGenerationDescriptorV2
from src.infrastructure.adapters.primary.web.startup.generation_http_v2 import (
    mount_generation_http_dispatcher_v2,
)
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.plugins.v2 import builtin_tenants_http_routes as subject
from src.infrastructure.plugins.v2.boundary import pin_operation_context_v2
from src.infrastructure.plugins.v2.builtin_http_routes import build_builtin_route_graph_v2
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.http_routes import RouteTableRegistryV2
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2


@pytest.mark.unit
def test_tenants_row_is_a_complete_explicit_v2_contribution() -> None:
    definitions = subject.tenants_route_definitions_v2()

    assert {
        (method, definition.path) for definition in definitions for method in definition.methods
    } == {
        ("POST", "/api/v1/tenants/"),
        ("GET", "/api/v1/tenants/"),
        ("GET", "/api/v1/tenants/{tenant_id}"),
        ("PUT", "/api/v1/tenants/{tenant_id}"),
        ("DELETE", "/api/v1/tenants/{tenant_id}"),
        ("POST", "/api/v1/tenants/{tenant_id}/members/{user_id}"),
        ("POST", "/api/v1/tenants/{tenant_id}/members"),
        ("PATCH", "/api/v1/tenants/{tenant_id}/members/{user_id}"),
        ("DELETE", "/api/v1/tenants/{tenant_id}/members/{user_id}"),
        ("GET", "/api/v1/tenants/{tenant_id}/members"),
        ("GET", "/api/v1/tenants/{tenant_id}/stats"),
        ("GET", "/api/v1/tenants/{tenant_id}/analytics"),
        ("GET", "/api/v1/tenants/{tenant_id}/gene-policies"),
        ("PUT", "/api/v1/tenants/{tenant_id}/gene-policies/{policy_key}"),
        ("DELETE", "/api/v1/tenants/{tenant_id}/gene-policies/{policy_key}"),
        ("GET", "/api/v1/tenants/{tenant_id}/registries"),
        ("POST", "/api/v1/tenants/{tenant_id}/registries"),
        ("PUT", "/api/v1/tenants/{tenant_id}/registries/{registry_id}"),
        ("DELETE", "/api/v1/tenants/{tenant_id}/registries/{registry_id}"),
        ("POST", "/api/v1/tenants/{tenant_id}/registries/{registry_id}/test"),
    }
    assert {definition.owner_entry_id for definition in definitions} == {
        subject.TENANTS_HTTP_ROUTES_ENTRY_V2
    }
    assert {definition.replaces_builtin_row_id for definition in definitions} == {"tenants"}


@pytest.mark.unit
def test_tenants_row_preserves_route_order_and_openapi() -> None:
    descriptor = PluginGenerationDescriptorV2(
        profile_id="tenants-route-parity",
        generation=1,
        digest="0" * 64,
    )
    baseline = build_builtin_route_graph_v2(
        workspace_core_settings=get_workspace_core_settings(),
    )
    claimed = build_builtin_route_graph_v2(
        workspace_core_settings=get_workspace_core_settings(),
        route_definitions=subject.tenants_route_definitions_v2(),
    )

    assert claimed.route_signatures == baseline.route_signatures
    assert (
        claimed.table.openapi_snapshot(descriptor).schema
        == baseline.table.openapi_snapshot(descriptor).schema
    )
    assert claimed.v2_owned_row_ids == ("tenants",)


@pytest.mark.unit
async def test_generation_dispatcher_executes_tenants_v2_before_static_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = object()
    db = object()
    calls: list[tuple[str, object, object]] = []

    async def list_handler(
        tenant_id: str,
        current_user: object,
        db_value: object,
    ) -> list[subject.RegistryResponse]:
        calls.append((tenant_id, current_user, db_value))
        return []

    async def current_user_override() -> object:
        return user

    async def db_override() -> object:
        return db

    monkeypatch.setattr(subject, "_list_registries", list_handler)
    graph = build_builtin_route_graph_v2(
        workspace_core_settings=get_workspace_core_settings(),
        route_definitions=subject.tenants_route_definitions_v2(),
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
    path = "/api/v1/tenants/tenant-1/registries"

    @outer.get(path)
    async def static_fallback() -> dict[str, str]:
        return {"source": "static"}

    async with (
        pin_operation_context_v2(
            host,
            operation_id="tenants-route-authority",
            scope=ScopeV2(kind=ScopeKindV2.ROOT),
        ),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=outer),
            base_url="http://test",
        ) as client,
    ):
        result = await client.get(path)

    assert result.status_code == 200
    assert result.json() == []
    assert calls == [("tenant-1", user, db)]
    await host.close()


@pytest.mark.unit
async def test_tenants_v2_handlers_preserve_tenant_member_and_analytics_arguments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    create_body = TenantCreate(name="Tenant")
    update_body = TenantUpdate(name="Updated")
    add_member_body = subject.AddMemberRequest(user_id="member-1", role="viewer")
    update_member_body = subject.UpdateMemberRoleRequest(role="admin")
    request = object()
    user = object()
    db = object()
    project_tenant = object()
    result = object()
    calls: list[tuple[str, tuple[object, ...]]] = []

    def handler(name: str, value: object = result) -> Any:
        async def call(*args: object) -> object:
            calls.append((name, args))
            return value

        return call

    monkeypatch.setattr(subject, "_create_tenant", handler("create"))
    monkeypatch.setattr(subject, "_list_tenants", handler("list"))
    monkeypatch.setattr(subject, "_get_tenant", handler("get"))
    monkeypatch.setattr(subject, "_update_tenant", handler("update"))
    monkeypatch.setattr(subject, "_delete_tenant", handler("delete", None))
    monkeypatch.setattr(subject, "_add_tenant_member", handler("add-member"))
    monkeypatch.setattr(subject, "_add_tenant_member_json", handler("add-member-json"))
    monkeypatch.setattr(subject, "_update_tenant_member_role", handler("update-member"))
    monkeypatch.setattr(subject, "_remove_tenant_member", handler("remove-member", None))
    monkeypatch.setattr(subject, "_list_tenant_members", handler("list-members"))
    monkeypatch.setattr(subject, "_get_tenant_stats", handler("stats"))
    monkeypatch.setattr(subject, "_get_tenant_analytics", handler("analytics"))

    assert await subject.create_tenant_v2(create_body, user, db) is result
    assert await subject.list_tenants_v2(2, 25, "needle", user, project_tenant) is result
    assert await subject.get_tenant_v2("tenant-1", user, db) is result
    assert await subject.update_tenant_v2("tenant-1", update_body, user, db) is result
    assert await subject.delete_tenant_v2("tenant-1", user, db) is None
    assert await subject.add_tenant_member_v2("tenant-1", "member-1", "viewer", user, db) is result
    assert await subject.add_tenant_member_json_v2("tenant-1", add_member_body, user, db) is result
    assert (
        await subject.update_tenant_member_role_v2(
            "tenant-1", "member-1", update_member_body, user, db
        )
        is result
    )
    assert await subject.remove_tenant_member_v2("tenant-1", "member-1", user, db) is None
    assert await subject.list_tenant_members_v2("tenant-1", request, user, db) is result
    assert await subject.get_tenant_stats_v2("tenant-1", user, db) is result
    assert await subject.get_tenant_analytics_v2("tenant-1", "90d", 15, user, db) is result

    assert calls == [
        ("create", (create_body, user, db)),
        ("list", (2, 25, "needle", user, project_tenant)),
        ("get", ("tenant-1", user, db)),
        ("update", ("tenant-1", update_body, user, db)),
        ("delete", ("tenant-1", user, db)),
        ("add-member", ("tenant-1", "member-1", "viewer", user, db)),
        ("add-member-json", ("tenant-1", add_member_body, user, db)),
        ("update-member", ("tenant-1", "member-1", update_member_body, user, db)),
        ("remove-member", ("tenant-1", "member-1", user, db)),
        ("list-members", ("tenant-1", request, user, db)),
        ("stats", ("tenant-1", user, db)),
        ("analytics", ("tenant-1", "90d", 15, user, db)),
    ]


@pytest.mark.unit
async def test_tenants_v2_handlers_preserve_gene_policy_and_registry_arguments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gene_body = subject.GenePolicyRequest(
        policy_key="memory-policy",
        policy_value={"enabled": True},
    )
    registry_body = subject.RegistryRequest(
        name="registry",
        registry_type="docker",
        url="https://registry.example.com",
    )
    user = object()
    db = object()
    result = object()
    calls: list[tuple[str, tuple[object, ...]]] = []

    def handler(name: str, value: object = result) -> Any:
        async def call(*args: object) -> object:
            calls.append((name, args))
            return value

        return call

    monkeypatch.setattr(subject, "_list_gene_policies", handler("list-gene-policies"))
    monkeypatch.setattr(subject, "_upsert_gene_policy", handler("upsert-gene-policy"))
    monkeypatch.setattr(subject, "_delete_gene_policy", handler("delete-gene-policy", None))
    monkeypatch.setattr(subject, "_list_registries", handler("list-registries"))
    monkeypatch.setattr(subject, "_create_registry", handler("create-registry"))
    monkeypatch.setattr(subject, "_update_registry", handler("update-registry"))
    monkeypatch.setattr(subject, "_delete_registry", handler("delete-registry", None))
    monkeypatch.setattr(subject, "_test_registry_connection", handler("test-registry"))

    assert await subject.list_gene_policies_v2("tenant-1", user, db) is result
    assert (
        await subject.upsert_gene_policy_v2("tenant-1", "memory-policy", gene_body, user, db)
        is result
    )
    assert await subject.delete_gene_policy_v2("tenant-1", "memory-policy", user, db) is None
    assert await subject.list_registries_v2("tenant-1", user, db) is result
    assert await subject.create_registry_v2("tenant-1", registry_body, user, db) is result
    assert (
        await subject.update_registry_v2("tenant-1", "registry-1", registry_body, user, db)
        is result
    )
    assert await subject.delete_registry_v2("tenant-1", "registry-1", user, db) is None
    assert await subject.test_registry_connection_v2("tenant-1", "registry-1", user, db) is result

    assert calls == [
        ("list-gene-policies", ("tenant-1", user, db)),
        ("upsert-gene-policy", ("tenant-1", "memory-policy", gene_body, user, db)),
        ("delete-gene-policy", ("tenant-1", "memory-policy", user, db)),
        ("list-registries", ("tenant-1", user, db)),
        ("create-registry", ("tenant-1", registry_body, user, db)),
        ("update-registry", ("tenant-1", "registry-1", registry_body, user, db)),
        ("delete-registry", ("tenant-1", "registry-1", user, db)),
        ("test-registry", ("tenant-1", "registry-1", user, db)),
    ]


@pytest.mark.unit
def test_tenants_module_definition_uses_generated_contract_binding() -> None:
    definition = subject.builtin_tenants_http_routes_definition_v2()

    assert definition.module_ref == subject.TENANTS_HTTP_ROUTES_MODULE_V2
    assert definition.contract_digest.startswith("sha256:")
