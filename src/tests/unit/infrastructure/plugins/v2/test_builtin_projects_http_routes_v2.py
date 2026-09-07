"""Production V2 ownership tests for the projects HTTP row."""

from __future__ import annotations

from inspect import signature
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from fastapi import FastAPI

from src.configuration.workspace_core import get_workspace_core_settings
from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.domain.model.plugins.runtime import PluginGenerationDescriptorV2
from src.infrastructure.adapters.primary.web.project_tenant_authority_v2 import (
    project_tenant_authority_dependency_v2,
)
from src.infrastructure.adapters.primary.web.routers import projects as project_routes
from src.infrastructure.adapters.primary.web.startup.generation_http_v2 import (
    mount_generation_http_dispatcher_v2,
)
from src.infrastructure.plugins.v2 import builtin_projects_http_routes as subject
from src.infrastructure.plugins.v2.boundary import pin_operation_context_v2
from src.infrastructure.plugins.v2.builtin_http_routes import build_builtin_route_graph_v2
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.http_routes import RouteTableRegistryV2
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2


@pytest.mark.unit
def test_projects_row_is_a_complete_explicit_v2_contribution() -> None:
    definitions = subject.projects_route_definitions_v2()

    assert {
        (method, definition.path) for definition in definitions for method in definition.methods
    } == {
        ("POST", "/api/v1/projects/"),
        ("GET", "/api/v1/projects/"),
        ("GET", "/api/v1/projects/{project_id}"),
        ("PUT", "/api/v1/projects/{project_id}"),
        ("DELETE", "/api/v1/projects/{project_id}"),
        ("POST", "/api/v1/projects/{project_id}/members"),
        ("PATCH", "/api/v1/projects/{project_id}/members/{user_id}"),
        ("DELETE", "/api/v1/projects/{project_id}/members/{user_id}"),
        ("GET", "/api/v1/projects/{project_id}/members"),
        ("GET", "/api/v1/projects/{project_id}/stats"),
        ("GET", "/api/v1/projects/{project_id}/trending"),
        ("GET", "/api/v1/projects/{project_id}/recent-skills"),
    }
    assert {definition.owner_entry_id for definition in definitions} == {
        subject.PROJECTS_HTTP_ROUTES_ENTRY_V2
    }
    assert {definition.replaces_builtin_row_id for definition in definitions} == {"projects"}


@pytest.mark.unit
def test_projects_row_registers_generation_owned_handlers_without_static_db_dependencies() -> None:
    endpoints = {
        definition.name: definition.endpoint
        for definition in subject.projects_route_definitions_v2()
    }
    expected = {
        "create_project": project_routes.create_project,
        "list_projects": project_routes.list_projects,
        "get_project": project_routes.get_project,
        "update_project": project_routes.update_project,
        "delete_project": project_routes.delete_project,
        "add_project_member": project_routes.add_project_member,
        "update_project_member": project_routes.update_project_member,
        "remove_project_member": project_routes.remove_project_member,
        "list_project_members": project_routes.list_project_members,
        "get_project_stats": project_routes.get_project_stats,
        "get_trending_entities": project_routes.get_trending_entities,
        "get_recent_skills": project_routes.get_recent_skills,
    }

    assert endpoints == expected
    for endpoint_name in (
        "delete_project",
        "add_project_member",
        "update_project_member",
        "remove_project_member",
        "list_project_members",
        "get_project_stats",
        "get_trending_entities",
        "get_recent_skills",
    ):
        parameters = signature(expected[endpoint_name]).parameters
        assert "db" not in parameters
        authority = parameters["project_tenant"]
        assert authority.default.dependency is project_tenant_authority_dependency_v2


@pytest.mark.unit
def test_projects_row_preserves_route_order_and_openapi() -> None:
    descriptor = PluginGenerationDescriptorV2(
        profile_id="projects-route-parity",
        generation=1,
        digest="0" * 64,
    )
    claimed = build_builtin_route_graph_v2(
        workspace_core_settings=get_workspace_core_settings(),
        route_definitions=subject.projects_route_definitions_v2(),
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
    assert claimed.v2_owned_row_ids == ("projects",)


@pytest.mark.unit
async def test_generation_dispatcher_executes_projects_v2_before_static_fallback() -> None:
    access_result = MagicMock()
    access_result.scalar_one_or_none.return_value = object()
    skills_result = MagicMock()
    skills_result.fetchall.return_value = []
    db = SimpleNamespace(execute=AsyncMock(side_effect=[access_result, skills_result]))
    response = project_routes.RecentSkillsResponse(skills=[])

    async def current_user_override() -> object:
        return SimpleNamespace(id="user-1")

    async def project_tenant_override() -> object:
        return SimpleNamespace(db=db)

    graph = build_builtin_route_graph_v2(
        workspace_core_settings=get_workspace_core_settings(),
        route_definitions=subject.projects_route_definitions_v2(),
        dependency_overrides={
            project_routes.get_current_user: current_user_override,
            project_tenant_authority_dependency_v2: project_tenant_override,
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
    path = "/api/v1/projects/project-1/recent-skills"

    @outer.get(path)
    async def static_fallback() -> dict[str, str]:
        return {"source": "static"}

    async with (
        pin_operation_context_v2(
            host,
            operation_id="projects-route-authority",
            scope=ScopeV2(kind=ScopeKindV2.ROOT),
        ),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=outer),
            base_url="http://test",
        ) as client,
    ):
        result = await client.get(path, params={"limit": 7})

    assert result.status_code == 200
    assert result.json() == response.model_dump(mode="json")
    assert db.execute.await_count == 2
    await host.close()


@pytest.mark.unit
def test_projects_module_definition_uses_generated_contract_binding() -> None:
    definition = subject.builtin_projects_http_routes_definition_v2()

    assert definition.module_ref == subject.PROJECTS_HTTP_ROUTES_MODULE_V2
    assert definition.contract_digest.startswith("sha256:")
