"""Production V2 ownership tests for workspace tool-grant HTTP routes."""

from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest
from fastapi import FastAPI, Request

from src.application.schemas.trust_schemas import (
    TrustPolicyListResponse,
    TrustPolicyResponse,
)
from src.configuration.workspace_core import get_workspace_core_settings
from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.domain.model.plugins.runtime import PluginGenerationDescriptorV2
from src.infrastructure.adapters.primary.web.startup.generation_http_v2 import (
    mount_generation_http_dispatcher_v2,
)
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.plugins.v2 import builtin_trust_workspace_http_routes as subject
from src.infrastructure.plugins.v2.boundary import pin_operation_context_v2
from src.infrastructure.plugins.v2.builtin_http_routes import build_builtin_route_graph_v2
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.http_routes import RouteTableRegistryV2
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2


def _policy_response() -> TrustPolicyResponse:
    return TrustPolicyResponse(
        id="policy-1",
        tenant_id="tenant-1",
        workspace_id="workspace-1",
        agent_instance_id="agent-1",
        action_type="tool.execute",
        granted_by="owner-1",
        grant_type="always",
        scope="workspace_tool",
        canonical_tool_name="terminal.exec",
        revision=1,
        created_at=datetime(2026, 8, 22, tzinfo=UTC),
    )


@pytest.mark.unit
def test_trust_workspace_row_is_a_complete_explicit_v2_contribution() -> None:
    definitions = subject.trust_workspace_route_definitions_v2()

    assert {
        (method, definition.path) for definition in definitions for method in definition.methods
    } == {
        (
            "GET",
            "/api/v1/tenants/{tenant_id}/projects/{project_id}/workspaces/"
            "{workspace_id}/tool-grants",
        ),
        (
            "DELETE",
            "/api/v1/tenants/{tenant_id}/projects/{project_id}/workspaces/"
            "{workspace_id}/tool-grants/{policy_id}",
        ),
    }
    assert {definition.owner_entry_id for definition in definitions} == {
        subject.TRUST_WORKSPACE_HTTP_ROUTES_ENTRY_V2
    }
    assert {definition.replaces_builtin_row_id for definition in definitions} == {"trust-workspace"}


@pytest.mark.unit
def test_trust_workspace_row_preserves_route_order_and_openapi() -> None:
    descriptor = PluginGenerationDescriptorV2(
        profile_id="trust-workspace-route-parity",
        generation=1,
        digest="0" * 64,
    )
    claimed = build_builtin_route_graph_v2(
        workspace_core_settings=get_workspace_core_settings(),
        route_definitions=subject.trust_workspace_route_definitions_v2(),
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
    assert claimed.v2_owned_row_ids == ("trust-workspace",)


@pytest.mark.unit
async def test_generation_dispatcher_executes_trust_workspace_v2_before_static_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = object()
    db = object()
    calls: list[tuple[str, str, str, str, object, object]] = []
    response = TrustPolicyListResponse(items=[])

    async def list_handler(
        tenant_id: str,
        project_id: str,
        workspace_id: str,
        request: Request,
        current_user: object,
        db_value: object,
    ) -> TrustPolicyListResponse:
        calls.append(
            (tenant_id, project_id, workspace_id, request.url.path, current_user, db_value)
        )
        return response

    async def current_user_override() -> object:
        return user

    async def db_override() -> object:
        return db

    monkeypatch.setattr(subject, "_list_workspace_tool_grants", list_handler)
    graph = build_builtin_route_graph_v2(
        workspace_core_settings=get_workspace_core_settings(),
        route_definitions=subject.trust_workspace_route_definitions_v2(),
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
    path = "/api/v1/tenants/tenant-1/projects/project-1/workspaces/workspace-1/tool-grants"

    @outer.get(path)
    async def static_fallback() -> dict[str, str]:
        return {"source": "static"}

    async with (
        pin_operation_context_v2(
            host,
            operation_id="trust-workspace-route-authority",
            scope=ScopeV2(kind=ScopeKindV2.ROOT),
        ),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=outer),
            base_url="http://test",
        ) as client,
    ):
        result = await client.get(path)

    assert result.status_code == 200
    assert result.json() == response.model_dump(mode="json")
    assert calls == [("tenant-1", "project-1", "workspace-1", path, user, db)]
    await host.close()


@pytest.mark.unit
async def test_trust_workspace_v2_handlers_preserve_security_scope_arguments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = object()
    user = object()
    db = object()
    listed = TrustPolicyListResponse(items=[])
    revoked = _policy_response()
    calls: list[tuple[str, tuple[object, ...]]] = []

    async def list_handler(*args: object) -> TrustPolicyListResponse:
        calls.append(("list", args))
        return listed

    async def revoke_handler(*args: object) -> TrustPolicyResponse:
        calls.append(("revoke", args))
        return revoked

    monkeypatch.setattr(subject, "_list_workspace_tool_grants", list_handler)
    monkeypatch.setattr(subject, "_revoke_workspace_tool_grant", revoke_handler)

    assert (
        await subject.list_workspace_tool_grants_v2(
            "tenant-1", "project-1", "workspace-1", request, user, db
        )
        == listed
    )
    assert (
        await subject.revoke_workspace_tool_grant_v2(
            "tenant-1",
            "project-1",
            "workspace-1",
            "policy-1",
            request,
            user,
            db,
        )
        == revoked
    )
    assert calls == [
        ("list", ("tenant-1", "project-1", "workspace-1", request, user, db)),
        (
            "revoke",
            (
                "tenant-1",
                "project-1",
                "workspace-1",
                "policy-1",
                request,
                user,
                db,
            ),
        ),
    ]


@pytest.mark.unit
def test_trust_workspace_module_definition_uses_generated_contract_binding() -> None:
    definition = subject.builtin_trust_workspace_http_routes_definition_v2()

    assert definition.module_ref == subject.TRUST_WORKSPACE_HTTP_ROUTES_MODULE_V2
    assert definition.contract_digest.startswith("sha256:")
