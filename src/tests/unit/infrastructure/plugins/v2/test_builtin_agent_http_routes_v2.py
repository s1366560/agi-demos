"""Production V2 ownership tests for the builtin agent HTTP row."""

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
from src.infrastructure.adapters.primary.web.routers.agent import router as legacy_agent_router
from src.infrastructure.agent.subagent.run_registry import SubAgentRunRegistry
from src.infrastructure.plugins.v2 import builtin_agent_http_routes as subject
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

_PREFIX = "/api/v1/agent"
type ExpectedRoute = tuple[str, str, str]
type DependencySignature = tuple[
    str | None,
    bool,
    tuple[str, ...],
    tuple[str, ...],
    tuple[Any, ...],
]

_EXPECTED_ROUTES: tuple[ExpectedRoute, ...] = (
    ("GET", "/commands", "list_commands"),
    ("POST", "/conversations", "create_conversation"),
    ("GET", "/conversations", "list_conversations"),
    ("GET", "/conversations/{conversation_id}", "get_conversation"),
    ("GET", "/conversations/{conversation_id}/context-status", "get_context_status"),
    ("DELETE", "/conversations/{conversation_id}", "delete_conversation"),
    ("PATCH", "/conversations/{conversation_id}/title", "update_conversation_title"),
    ("PATCH", "/conversations/{conversation_id}/config", "update_conversation_config"),
    ("PATCH", "/conversations/{conversation_id}/mode", "update_conversation_mode"),
    ("POST", "/conversations/{conversation_id}/generate-title", "generate_conversation_title"),
    ("POST", "/conversations/{conversation_id}/summary", "generate_summary"),
    ("POST", "/conversations/{conversation_id}/fork", "fork_conversation"),
    ("PUT", "/conversations/{conversation_id}/messages/{message_id}", "edit_message"),
    ("POST", "/conversations/{conversation_id}/tools/{execution_id}/undo", "request_tool_undo"),
    ("GET", "/conversations/{conversation_id}/participants", "list_participants"),
    ("POST", "/conversations/{conversation_id}/participants", "add_participant"),
    ("DELETE", "/conversations/{conversation_id}/participants/{agent_id}", "remove_participant"),
    ("PATCH", "/conversations/{conversation_id}/participants/coordinator", "set_coordinator"),
    ("PATCH", "/conversations/{conversation_id}/participants/focused", "set_focused_agent"),
    ("GET", "/conversations/{conversation_id}/mention-candidates", "list_mention_candidates"),
    ("GET", "/conversations/{conversation_id}/messages", "get_conversation_messages"),
    ("GET", "/conversations/{conversation_id}/execution", "get_conversation_execution"),
    ("GET", "/conversations/{conversation_id}/tool-executions", "get_conversation_tool_executions"),
    ("GET", "/conversations/{conversation_id}/status", "get_conversation_execution_status"),
    ("GET", "/conversations/{conversation_id}/execution/stats", "get_execution_stats"),
    (
        "GET",
        "/conversations/{conversation_id}/messages/{message_id}/replies",
        "get_message_replies",
    ),
    ("GET", "/tools", "list_tools"),
    ("GET", "/tools/capabilities", "get_tool_capabilities"),
    ("GET", "/tools/compositions", "list_tool_compositions"),
    ("GET", "/tools/compositions/{composition_id}", "get_tool_composition"),
    ("POST", "/debug/tool-policy", "debug_tool_policy"),
    ("GET", "/workflows/patterns/project/{project_id}", "list_project_shared_patterns"),
    ("GET", "/workflows/patterns", "list_patterns"),
    ("GET", "/workflows/patterns/{pattern_id}", "get_pattern"),
    ("DELETE", "/workflows/patterns/{pattern_id}", "delete_pattern"),
    ("POST", "/workflows/patterns/reset", "reset_patterns"),
    ("GET", "/config/can-modify", "check_config_modify_permission"),
    ("GET", "/config", "get_tenant_agent_config"),
    ("GET", "/config/authority-revision", "get_tenant_agent_config_authority_revision"),
    ("GET", "/config/hooks/catalog", "get_hook_catalog"),
    ("PUT", "/config", "update_tenant_agent_config"),
    ("GET", "/hitl/conversations/{conversation_id}/pending", "get_pending_hitl_requests"),
    ("GET", "/hitl/projects/{project_id}/pending", "get_project_pending_hitl_requests"),
    ("POST", "/hitl/respond", "respond_to_hitl"),
    ("POST", "/hitl/cancel", "cancel_hitl_request"),
    ("GET", "/conversations/{conversation_id}/events", "get_conversation_events"),
    ("GET", "/conversations/{conversation_id}/execution-status", "get_execution_status"),
    ("POST", "/conversations/{conversation_id}/resume", "resume_execution"),
    ("GET", "/conversations/{conversation_id}/workflow-status", "get_workflow_status"),
    ("POST", "/templates", "create_template"),
    ("GET", "/templates", "list_templates"),
    ("GET", "/templates/{template_id}", "get_template"),
    ("PUT", "/templates/{template_id}", "update_template"),
    ("DELETE", "/templates/{template_id}", "delete_template"),
    ("POST", "/plan/mode", "switch_mode"),
    ("GET", "/plan/mode/{conversation_id}", "get_mode"),
    ("GET", "/plan/tasks/{conversation_id}", "get_tasks"),
    ("POST", "/plans/approve-and-start", "approve_plan_and_start"),
    ("POST", "/runs/{run_id}/inputs", "create_run_input"),
    ("GET", "/runs/{run_id}/inputs", "list_run_inputs"),
    ("POST", "/runs/{run_id}/inputs/{input_id}/promote", "promote_run_input"),
    ("GET", "/conversations/{conversation_id}/active-run", "get_active_run"),
    ("GET", "/conversations/{conversation_id}/latest-run", "get_latest_run"),
    ("GET", "/runs/{run_id}/summary", "get_run_summary"),
    ("GET", "/runs/{run_id}/changes", "get_run_changes"),
    ("GET", "/conversations/{conversation_id}/session", "get_conversation_session_projection"),
    ("POST", "/subagent/{execution_id}/cancel", "cancel_subagent_execution"),
    ("POST", "/bindings", "create_binding"),
    ("GET", "/bindings", "list_bindings"),
    ("DELETE", "/bindings/{binding_id}", "delete_binding"),
    ("PATCH", "/bindings/{binding_id}/enabled", "set_binding_enabled"),
    ("GET", "/bindings/groups/{group_id}", "list_group_bindings"),
    ("POST", "/bindings/test", "test_binding_match"),
    ("POST", "/definitions", "create_definition"),
    ("GET", "/definitions", "list_definitions"),
    ("GET", "/definitions/{definition_id}", "get_definition"),
    ("PUT", "/definitions/{definition_id}", "update_definition"),
    ("DELETE", "/definitions/{definition_id}", "delete_definition"),
    ("PATCH", "/definitions/{definition_id}/enabled", "set_definition_enabled"),
    ("GET", "/trace/runs/project/{project_id}/active/count", "get_project_active_run_count"),
    ("GET", "/trace/runs/project/{project_id}", "list_project_runs"),
    ("GET", "/trace/runs/tenant/{tenant_id}/active/count", "get_tenant_active_run_count"),
    ("GET", "/trace/runs/tenant/{tenant_id}", "list_tenant_runs"),
    ("GET", "/trace/runs/active/count", "get_active_run_count"),
    ("GET", "/trace/runs/{conversation_id}", "list_runs"),
    ("GET", "/trace/runs/{conversation_id}/trace/{trace_id}", "get_trace_chain"),
    ("GET", "/trace/runs/{conversation_id}/{run_id}/descendants", "get_descendants"),
    ("GET", "/trace/runs/{conversation_id}/{run_id}", "get_run"),
    ("GET", "/graphs", "list_graphs"),
    ("POST", "/graphs", "create_graph"),
    ("GET", "/graphs/{graph_id}", "get_graph"),
    ("PUT", "/graphs/{graph_id}", "update_graph"),
    ("DELETE", "/graphs/{graph_id}", "delete_graph"),
    ("POST", "/graphs/{graph_id}/runs", "start_graph_run"),
    ("GET", "/graphs/{graph_id}/runs", "list_graph_runs"),
    ("GET", "/graphs/runs/{run_id}", "get_graph_run"),
    ("POST", "/graphs/runs/{run_id}/cancel", "cancel_graph_run"),
)


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


def _dependency_signatures(
    app: FastAPI,
) -> tuple[tuple[str, str, DependencySignature], ...]:
    return tuple(
        (route.path, next(iter(route.methods)), _dependant_signature(route.dependant))
        for route in app.router.routes
        if isinstance(route, APIRoute)
    )


def _immediate_dependency_ids(app: FastAPI) -> list[str]:
    return [
        cast(str, _callable_id(dependency.call))
        for route in app.router.routes
        if isinstance(route, APIRoute)
        for dependency in route.dependant.dependencies
    ]


def _legacy_route_map() -> dict[tuple[str, str], APIRoute]:
    return {
        (next(iter(route.methods)), route.path): route
        for route in legacy_agent_router.routes
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
        self.registry = SubAgentRunRegistry()
        self.teardown = teardown
        self.required_services: list[str] = []
        self.effect_labels: list[str] = []

    def require(self, service: str) -> object:
        self.required_services.append(service)
        if service == ROUTE_TABLE_BUILDER_INJECT_V2:
            return self.builder
        if service == subject.AGENT_HTTP_SUBAGENT_RUNS_INJECT_V2:
            return self.registry
        raise AssertionError(f"unexpected service request: {service}")

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


def test_agent_row_is_a_complete_explicit_v2_contribution() -> None:
    definitions = subject.agent_route_definitions_v2()
    legacy = _legacy_route_map()

    assert len(definitions) == 97
    assert tuple(_route_signature(definition) for definition in definitions) == _EXPECTED_ROUTES
    assert len(legacy) == len(definitions)
    for definition in definitions:
        route = legacy[(definition.methods[0], definition.path)]
        assert definition.endpoint is route.endpoint
        assert definition.response_model == route.response_model
        assert definition.status_code == route.status_code
        assert definition.tags == tuple(route.tags)
        assert definition.deprecated == route.deprecated
    assert Counter(definition.methods[0] for definition in definitions) == {
        "DELETE": 7,
        "GET": 55,
        "PATCH": 7,
        "POST": 23,
        "PUT": 5,
    }
    assert {definition.owner_entry_id for definition in definitions} == {
        subject.AGENT_HTTP_ROUTES_ENTRY_V2
    }
    assert {definition.replaces_builtin_row_id for definition in definitions} == {"agent"}
    assert all(definition.summary is None for definition in definitions)
    assert all(definition.description is None for definition in definitions)
    assert all(definition.include_in_schema for definition in definitions)
    assert [definition.path for definition in definitions if definition.deprecated] == [
        f"{_PREFIX}/conversations/{{conversation_id}}/generate-title"
    ]
    assert Counter(definition.tags for definition in definitions) == {
        ("agent",): 93,
        ("agent", "plan"): 4,
    }
    source = inspect.getsource(subject)
    assert ".router.routes" not in source
    assert "legacy_agent_router" not in source


def test_agent_row_preserves_route_order_openapi_and_recursive_dependencies() -> None:
    descriptor = PluginGenerationDescriptorV2(
        profile_id="agent-route-parity",
        generation=1,
        digest="0" * 64,
    )
    claimed = build_builtin_route_graph_v2(
        workspace_core_settings=get_workspace_core_settings(),
        route_definitions=subject.agent_route_definitions_v2(),
    )
    legacy_app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    legacy_app.include_router(legacy_agent_router)
    claimed_app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    install_route_definitions_v2(claimed_app, subject.agent_route_definitions_v2())

    assert claimed.route_signatures == tuple(
        (
            definition.path,
            definition.name,
            () if definition.methods == ("WEBSOCKET",) else tuple(sorted(definition.methods)),
        )
        for definition in claimed.table.definitions
    )
    assert claimed.table.openapi_snapshot(descriptor).schema["openapi"].startswith("3.")
    assert _dependency_signatures(claimed_app) == _dependency_signatures(legacy_app)
    assert Counter(_immediate_dependency_ids(claimed_app)) == {
        "src.infrastructure.adapters.primary.web.conversation_collection_http_application_authority_v2.conversation_create_http_application_authority_dependency_v2": 1,
        "src.infrastructure.adapters.primary.web.conversation_collection_http_application_authority_v2.conversation_list_http_application_authority_dependency_v2": 1,
        "src.infrastructure.adapters.primary.web.conversation_config_http_application_authority_v2.conversation_config_http_application_authority_dependency_v2": 1,
        "src.infrastructure.adapters.primary.web.conversation_context_status_http_application_authority_v2.conversation_context_status_http_application_authority_dependency_v2": 1,
        "src.infrastructure.adapters.primary.web.conversation_generation_http_application_authority_v2.conversation_generation_http_application_authority_dependency_v2": 2,
        "src.infrastructure.adapters.primary.web.conversation_http_application_authority_v2.conversation_http_application_authority_dependency_v2": 4,
        "src.infrastructure.adapters.primary.web.conversation_participant_http_application_authority_v2.conversation_participant_http_application_authority_dependency_v2": 6,
        "src.infrastructure.adapters.primary.web.conversation_revision_http_application_authority_v2.conversation_revision_http_application_authority_dependency_v2": 3,
        "src.infrastructure.adapters.primary.web.agent_event_query_http_application_authority_v2.agent_event_query_http_application_authority_dependency_v2": 2,
        "src.infrastructure.adapters.primary.web.agent_execution_query_application_authority_v2.agent_execution_query_application_authority_dependency_v2": 2,
        "src.infrastructure.adapters.primary.web.routers.agent.binding_router.agent_binding_http_application_authority_dependency_v2": 6,
        "src.infrastructure.adapters.primary.web.dependencies.auth_dependencies.get_current_user": 92,
        "src.infrastructure.adapters.primary.web.dependencies.auth_dependencies.get_current_user_tenant": 31,
        "src.infrastructure.adapters.primary.web.project_access_http_application_authority_v2.project_access_create_http_application_authority_dependency_v2": 1,
        "src.infrastructure.adapters.primary.web.project_access_http_application_authority_v2.project_access_query_http_application_authority_dependency_v2": 9,
        "src.infrastructure.adapters.primary.web.routers.agent.definitions_router._get_selected_definition_tenant_id": 6,
        "src.infrastructure.adapters.primary.web.workflow_pattern_application_authority_v2.workflow_pattern_application_authority_dependency_v2": 5,
        "src.infrastructure.adapters.secondary.persistence.database.get_db": 63,
    }
    assert claimed.v2_owned_row_ids == ("agent",)


def test_agent_module_definition_uses_generated_contract_binding() -> None:
    definition = subject.builtin_agent_http_routes_definition_v2()

    assert definition.module_ref == subject.AGENT_HTTP_ROUTES_MODULE_V2
    assert definition.contract_digest.startswith("sha256:")


async def test_agent_route_effect_teardown_disposes_all_contributions_in_lifo_order() -> None:
    builder = _RecordingBuilder()
    context = _FakeContext(builder, teardown=True)
    definition = subject.builtin_agent_http_routes_definition_v2()

    await definition.apply(cast("ContextV2", context), {})

    expected = [name for _method, _path, name in _EXPECTED_ROUTES]
    assert builder.registered == expected
    assert builder.disposed == list(reversed(expected))
    assert context.required_services == [
        ROUTE_TABLE_BUILDER_INJECT_V2,
        subject.AGENT_HTTP_SUBAGENT_RUNS_INJECT_V2,
    ]
    assert context.effect_labels == [subject.AGENT_HTTP_ROUTES_ENTRY_V2]


async def test_agent_route_partial_setup_disposes_contributions_in_lifo_order() -> None:
    builder = _RecordingBuilder(fail_after=3)
    context = _FakeContext(builder, teardown=False)
    definition = subject.builtin_agent_http_routes_definition_v2()

    with pytest.raises(RuntimeError, match="planned contribution failure"):
        await definition.apply(cast("ContextV2", context), {})

    assert builder.registered == ["list_commands", "create_conversation", "list_conversations"]
    assert builder.disposed == list(reversed(builder.registered))
    assert context.required_services == [
        ROUTE_TABLE_BUILDER_INJECT_V2,
        subject.AGENT_HTTP_SUBAGENT_RUNS_INJECT_V2,
    ]
    assert context.effect_labels == [subject.AGENT_HTTP_ROUTES_ENTRY_V2]
