"""Production V2 ownership tests for the builtin skills HTTP row."""

from __future__ import annotations

import inspect
from collections import Counter
from typing import TYPE_CHECKING, Any, cast

import pytest
from fastapi import FastAPI
from fastapi.dependencies.models import Dependant
from fastapi.routing import APIRoute

from src.configuration.workspace_core import get_workspace_core_settings
from src.domain.model.plugins.runtime import PluginGenerationDescriptorV2
from src.infrastructure.adapters.primary.web.routers.skills import router as legacy_skills_router
from src.infrastructure.plugins.v2 import builtin_skills_http_routes as subject
from src.infrastructure.plugins.v2.builtin_http_routes import build_builtin_route_graph_v2
from src.infrastructure.plugins.v2.http_routes import (
    RouteDefinitionV2,
    RouteTableBuilderV2,
    install_route_definitions_v2,
)
from src.infrastructure.plugins.v2.route_effects import ROUTE_TABLE_BUILDER_INJECT_V2

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from src.infrastructure.plugins.v2.runtime import ContextV2

pytestmark = pytest.mark.unit

_PREFIX = "/api/v1/skills"
type ExpectedRoute = tuple[str, str, str]
type DependencySignature = tuple[
    str | None,
    bool,
    tuple[str, ...],
    tuple[str, ...],
    tuple[Any, ...],
]

_EXPECTED_ROUTES: tuple[ExpectedRoute, ...] = (
    ("POST", "/", "create_skill"),
    ("GET", "/", "list_skills"),
    ("GET", "/{skill_id}", "get_skill"),
    ("PUT", "/{skill_id}", "update_skill"),
    ("DELETE", "/{skill_id}", "delete_skill"),
    ("PATCH", "/{skill_id}/status", "update_skill_status"),
    ("GET", "/system/list", "list_system_skills"),
    ("GET", "/{skill_id}/content", "get_skill_content"),
    ("PUT", "/{skill_id}/content", "update_skill_content"),
    ("POST", "/import", "import_skill_package"),
    ("POST", "/import/zip", "import_skill_zip_package"),
    ("GET", "/{skill_id}/export", "export_skill_package"),
    ("GET", "/evolution/config", "get_skill_evolution_config"),
    ("PUT", "/evolution/config", "update_skill_evolution_config"),
    ("GET", "/evolution/overview", "get_skill_evolution_overview"),
    ("POST", "/evolution/jobs/{job_id}/apply", "apply_skill_evolution_job"),
    ("POST", "/evolution/jobs/{job_id}/reject", "reject_skill_evolution_job"),
    ("POST", "/evolution/run", "run_tenant_skill_evolution"),
    ("GET", "/{skill_id}/evolution", "get_skill_evolution"),
    ("POST", "/{skill_id}/evolution/run", "run_skill_evolution"),
    ("GET", "/{skill_id}/versions", "list_skill_versions"),
    ("GET", "/{skill_id}/versions/{version_number}", "get_skill_version"),
    ("POST", "/{skill_id}/rollback", "rollback_skill"),
)

_EXPLICIT_SUMMARIES = {
    "import_skill_package": "Import an AgentSkills.io package",
    "import_skill_zip_package": "Import an AgentSkills.io zip package",
    "export_skill_package": "Export a skill as an AgentSkills.io package",
    "get_skill_evolution_config": "Get skill evolution strategy config",
    "update_skill_evolution_config": "Update skill evolution strategy config",
    "get_skill_evolution_overview": "Get skill evolution overview",
    "apply_skill_evolution_job": "Apply a pending skill evolution job",
    "reject_skill_evolution_job": "Reject a pending skill evolution job",
    "run_tenant_skill_evolution": "Run tenant skill evolution now",
    "get_skill_evolution": "Get skill evolution route",
    "run_skill_evolution": "Run skill evolution now",
    "list_skill_versions": "List skill versions",
    "get_skill_version": "Get skill version detail",
    "rollback_skill": "Rollback skill to a previous version",
}


def _route_signature(definition: RouteDefinitionV2) -> ExpectedRoute:
    return (
        definition.methods[0],
        definition.path.removeprefix(_PREFIX),
        definition.name,
    )


def _callable_id(value: object | None) -> str | None:
    if value is None:
        return None
    return f"{getattr(value, '__module__', '?')}.{getattr(value, '__qualname__', repr(value))}"


def _dependant_signature(dependant: Dependant) -> DependencySignature:
    return (
        _callable_id(dependant.call),
        dependant.use_cache,
        tuple(dependant.own_oauth_scopes or ()),
        tuple(dependant.parent_oauth_scopes or ()),
        tuple(_dependant_signature(child) for child in dependant.dependencies),
    )


def _dependency_signatures(app: FastAPI) -> tuple[tuple[str, str, DependencySignature], ...]:
    return tuple(
        (route.path, next(iter(route.methods)), _dependant_signature(route.dependant))
        for route in app.router.routes
        if isinstance(route, APIRoute)
    )


def _legacy_route_map() -> dict[tuple[str, str], APIRoute]:
    return {
        (next(iter(route.methods)), route.path): route
        for route in legacy_skills_router.routes
        if isinstance(route, APIRoute)
    }


class _RecordingBuilder(RouteTableBuilderV2):
    def __init__(self, *, fail_after: int | None = None) -> None:
        self.fail_after = fail_after
        self.registered: list[str] = []
        self.disposed: list[str] = []

    def contribute(
        self,
        definition: RouteDefinitionV2,
    ) -> Callable[[], Awaitable[None]]:
        if self.fail_after is not None and len(self.registered) == self.fail_after:
            raise RuntimeError("planned contribution failure")
        self.registered.append(definition.name)

        async def dispose() -> None:
            self.disposed.append(definition.name)

        return dispose


class _FakeContext:
    def __init__(self, builder: RouteTableBuilderV2, *, teardown: bool) -> None:
        self.builder = builder
        self.teardown = teardown
        self.required_services: list[str] = []
        self.effect_labels: list[str] = []

    def require(self, service: str) -> object:
        self.required_services.append(service)
        return self.builder

    async def effect(
        self,
        setup: Callable[[], Awaitable[object]],
        *,
        label: str,
    ) -> None:
        self.effect_labels.append(label)
        result = await setup()
        if self.teardown:
            disposers = cast("tuple[Callable[[], Awaitable[None]], ...]", result)
            for dispose in reversed(disposers):
                await dispose()


def test_skills_row_is_a_complete_explicit_v2_contribution() -> None:
    definitions = subject.skills_route_definitions_v2()
    legacy = _legacy_route_map()

    assert len(definitions) == 23
    assert tuple(_route_signature(definition) for definition in definitions) == _EXPECTED_ROUTES
    assert len(legacy) == len(definitions)
    for definition in definitions:
        route = legacy[(definition.methods[0], definition.path)]
        assert definition.endpoint is route.endpoint
        assert definition.response_model == route.response_model
        assert definition.status_code == route.status_code
        assert definition.tags == tuple(route.tags)
        assert definition.summary == route.summary
        assert definition.deprecated == route.deprecated
    assert Counter(definition.methods[0] for definition in definitions) == {
        "DELETE": 1,
        "GET": 10,
        "PATCH": 1,
        "POST": 8,
        "PUT": 3,
    }
    assert {definition.owner_entry_id for definition in definitions} == {
        subject.SKILLS_HTTP_ROUTES_ENTRY_V2
    }
    assert {definition.replaces_builtin_row_id for definition in definitions} == {"skills"}
    assert {definition.tags for definition in definitions} == {("Skills",)}
    assert {
        definition.name: definition.summary
        for definition in definitions
        if definition.summary is not None
    } == _EXPLICIT_SUMMARIES
    assert all(definition.description is None for definition in definitions)
    assert all(definition.deprecated is None for definition in definitions)
    assert all(definition.include_in_schema for definition in definitions)
    source = inspect.getsource(subject)
    assert ".router.routes" not in source
    assert "legacy_skills_router" not in source


def test_skills_row_preserves_route_order_openapi_and_recursive_dependencies() -> None:
    descriptor = PluginGenerationDescriptorV2(
        profile_id="skills-route-parity",
        generation=1,
        digest="0" * 64,
    )
    claimed = build_builtin_route_graph_v2(
        workspace_core_settings=get_workspace_core_settings(),
        route_definitions=subject.skills_route_definitions_v2(),
    )
    legacy_app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    legacy_app.include_router(legacy_skills_router)
    claimed_app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    install_route_definitions_v2(claimed_app, subject.skills_route_definitions_v2())

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
    assert _dependency_signatures(claimed_app) == _dependency_signatures(legacy_app)
    assert claimed.v2_owned_row_ids == ("skills",)


def test_skills_module_definition_uses_generated_contract_binding() -> None:
    definition = subject.builtin_skills_http_routes_definition_v2()

    assert definition.module_ref == subject.SKILLS_HTTP_ROUTES_MODULE_V2
    assert definition.contract_digest.startswith("sha256:")


async def test_skills_route_effect_teardown_disposes_all_contributions_in_lifo_order() -> None:
    builder = _RecordingBuilder()
    context = _FakeContext(builder, teardown=True)
    definition = subject.builtin_skills_http_routes_definition_v2()

    await definition.apply(cast("ContextV2", context), {})

    expected = [name for _method, _path, name in _EXPECTED_ROUTES]
    assert builder.registered == expected
    assert builder.disposed == list(reversed(expected))
    assert context.required_services == [ROUTE_TABLE_BUILDER_INJECT_V2]
    assert context.effect_labels == [subject.SKILLS_HTTP_ROUTES_ENTRY_V2]


async def test_skills_route_partial_setup_disposes_contributions_in_lifo_order() -> None:
    builder = _RecordingBuilder(fail_after=3)
    context = _FakeContext(builder, teardown=False)
    definition = subject.builtin_skills_http_routes_definition_v2()

    with pytest.raises(RuntimeError, match="planned contribution failure"):
        await definition.apply(cast("ContextV2", context), {})

    assert builder.registered == ["create_skill", "list_skills", "get_skill"]
    assert builder.disposed == list(reversed(builder.registered))
    assert context.required_services == [ROUTE_TABLE_BUILDER_INJECT_V2]
    assert context.effect_labels == [subject.SKILLS_HTTP_ROUTES_ENTRY_V2]
