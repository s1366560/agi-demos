"""Production V2 ownership tests for the projects HTTP row."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from src.application.schemas.project import (
    ProjectCreate,
    ProjectMemberUpdate,
    ProjectUpdate,
)
from src.configuration.workspace_core import get_workspace_core_settings
from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.domain.model.plugins.runtime import PluginGenerationDescriptorV2
from src.infrastructure.adapters.primary.web.startup.generation_http_v2 import (
    mount_generation_http_dispatcher_v2,
)
from src.infrastructure.adapters.secondary.persistence.database import get_db
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
            ()
            if definition.methods == ("WEBSOCKET",)
            else tuple(sorted(definition.methods)),
        )
        for definition in claimed.table.definitions
    )
    assert claimed.table.openapi_snapshot(descriptor).schema["openapi"].startswith("3.")
    assert claimed.v2_owned_row_ids == ("projects",)


@pytest.mark.unit
async def test_generation_dispatcher_executes_projects_v2_before_static_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = object()
    db = object()
    calls: list[tuple[str, int, object, object]] = []
    response = subject.RecentSkillsResponse(skills=[])

    async def recent_skills_handler(
        project_id: str,
        limit: int,
        current_user: object,
        db_value: object,
    ) -> subject.RecentSkillsResponse:
        calls.append((project_id, limit, current_user, db_value))
        return response

    async def current_user_override() -> object:
        return user

    async def db_override() -> object:
        return db

    monkeypatch.setattr(subject, "_get_recent_skills", recent_skills_handler)
    graph = build_builtin_route_graph_v2(
        workspace_core_settings=get_workspace_core_settings(),
        route_definitions=subject.projects_route_definitions_v2(),
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
    assert calls == [("project-1", 7, user, db)]
    await host.close()


@pytest.mark.unit
async def test_projects_v2_handlers_preserve_all_authority_and_database_arguments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    create_body = ProjectCreate(name="Project", tenant_id="tenant-1")
    update_body = ProjectUpdate(name="Updated")
    add_member_body = subject.AddProjectMemberRequest(user_id="member-1", role="viewer")
    update_member_body = ProjectMemberUpdate(role="admin")
    user = object()
    db = object()
    graph_store = object()
    project_tenant = object()
    backend_store = object()
    result = object()
    calls: list[tuple[str, tuple[object, ...]]] = []

    def handler(name: str, value: object = result) -> Any:
        async def call(*args: object) -> object:
            calls.append((name, args))
            return value

        return call

    monkeypatch.setattr(subject, "_create_project", handler("create"))
    monkeypatch.setattr(subject, "_list_projects", handler("list"))
    monkeypatch.setattr(subject, "_get_project", handler("get"))
    monkeypatch.setattr(subject, "_update_project", handler("update"))
    monkeypatch.setattr(subject, "_delete_project", handler("delete", None))
    monkeypatch.setattr(subject, "_add_project_member", handler("add-member"))
    monkeypatch.setattr(subject, "_update_project_member", handler("update-member"))
    monkeypatch.setattr(subject, "_remove_project_member", handler("remove-member", None))
    monkeypatch.setattr(subject, "_list_project_members", handler("list-members"))
    monkeypatch.setattr(subject, "_get_project_stats", handler("stats"))
    monkeypatch.setattr(subject, "_get_trending_entities", handler("trending"))
    monkeypatch.setattr(subject, "_get_recent_skills", handler("recent-skills"))

    assert await subject.create_project_v2(create_body, user, backend_store) is result
    assert (
        await subject.list_projects_v2(
            "tenant-1",
            2,
            25,
            "needle",
            "private",
            "owner-1",
            user,
            graph_store,
            project_tenant,
            backend_store,
        )
        is result
    )
    assert await subject.get_project_v2("project-1", "tenant-1", user, backend_store) is result
    assert await subject.update_project_v2("project-1", update_body, user, backend_store) is result
    assert await subject.delete_project_v2("project-1", user, db) is None
    assert await subject.add_project_member_v2("project-1", add_member_body, user, db) is result
    assert (
        await subject.update_project_member_v2(
            "project-1", "member-1", update_member_body, user, db
        )
        is result
    )
    assert await subject.remove_project_member_v2("project-1", "member-1", user, db) is None
    assert await subject.list_project_members_v2("project-1", user, db) is result
    assert await subject.get_project_stats_v2("project-1", user, db, graph_store) is result
    assert await subject.get_trending_entities_v2("project-1", 7, user, db, graph_store) is result
    assert await subject.get_recent_skills_v2("project-1", 6, user, db) is result

    assert calls == [
        ("create", (create_body, user, backend_store)),
        (
            "list",
            (
                "tenant-1",
                2,
                25,
                "needle",
                "private",
                "owner-1",
                user,
                graph_store,
                project_tenant,
                backend_store,
            ),
        ),
        ("get", ("project-1", "tenant-1", user, backend_store)),
        ("update", ("project-1", update_body, user, backend_store)),
        ("delete", ("project-1", user, db)),
        ("add-member", ("project-1", add_member_body, user, db)),
        ("update-member", ("project-1", "member-1", update_member_body, user, db)),
        ("remove-member", ("project-1", "member-1", user, db)),
        ("list-members", ("project-1", user, db)),
        ("stats", ("project-1", user, db, graph_store)),
        ("trending", ("project-1", 7, user, db, graph_store)),
        ("recent-skills", ("project-1", 6, user, db)),
    ]


@pytest.mark.unit
def test_projects_module_definition_uses_generated_contract_binding() -> None:
    definition = subject.builtin_projects_http_routes_definition_v2()

    assert definition.module_ref == subject.PROJECTS_HTTP_ROUTES_MODULE_V2
    assert definition.contract_digest.startswith("sha256:")
