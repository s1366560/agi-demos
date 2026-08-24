"""Production V2 ownership tests for the builtin tasks HTTP row."""

from __future__ import annotations

from typing import Any

import pytest
from sse_starlette.sse import EventSourceResponse

from src.configuration.workspace_core import get_workspace_core_settings
from src.domain.model.plugins.runtime import PluginGenerationDescriptorV2
from src.infrastructure.adapters.primary.web.routers.tasks import (
    QueueDepthPoint,
    RecentTasksResponse,
    RetryPendingResponse,
    TaskLogResponse,
    TaskStatsResponse,
)
from src.infrastructure.plugins.v2 import builtin_tasks_http_routes as subject
from src.infrastructure.plugins.v2.builtin_http_routes import build_builtin_route_graph_v2

pytestmark = pytest.mark.unit


def test_tasks_row_is_a_complete_explicit_v2_contribution() -> None:
    definitions = subject.task_route_definitions_v2()
    prefix = "/api/v1/tasks"

    assert tuple(
        (
            definition.path,
            definition.methods,
            definition.name,
            definition.response_model,
            definition.response_class,
        )
        for definition in definitions
    ) == (
        (f"{prefix}/stats", ("GET",), "get_task_stats", TaskStatsResponse, None),
        (f"{prefix}/queue-depth", ("GET",), "get_queue_depth", list[QueueDepthPoint], None),
        (f"{prefix}/recent", ("GET",), "get_recent_tasks", RecentTasksResponse, None),
        (
            f"{prefix}/status-breakdown",
            ("GET",),
            "get_status_breakdown",
            dict[str, Any],
            None,
        ),
        (
            f"{prefix}/retry-pending",
            ("POST",),
            "retry_pending_tasks_endpoint",
            RetryPendingResponse,
            None,
        ),
        (
            f"{prefix}/{{task_id}}/retry",
            ("POST",),
            "retry_task_endpoint",
            dict[str, Any],
            None,
        ),
        (
            f"{prefix}/{{task_id}}/stop",
            ("POST",),
            "stop_task_endpoint",
            dict[str, Any],
            None,
        ),
        (
            f"{prefix}/{{task_id}}/stream",
            ("GET",),
            "stream_task_status",
            None,
            EventSourceResponse,
        ),
        (f"{prefix}/{{task_id}}", ("GET",), "get_task_status", TaskLogResponse, None),
        (f"{prefix}/{{task_id}}/cancel", ("POST",), "cancel_task_endpoint", Any, None),
    )
    assert {definition.tags for definition in definitions} == {("tasks",)}
    assert {definition.owner_entry_id for definition in definitions} == {
        subject.TASKS_HTTP_ROUTES_ENTRY_V2
    }
    assert {definition.replaces_builtin_row_id for definition in definitions} == {"tasks"}


def test_tasks_row_preserves_route_order_and_openapi() -> None:
    descriptor = PluginGenerationDescriptorV2(
        profile_id="tasks-route-parity",
        generation=1,
        digest="0" * 64,
    )
    claimed = build_builtin_route_graph_v2(
        workspace_core_settings=get_workspace_core_settings(),
        route_definitions=subject.task_route_definitions_v2(),
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
    assert claimed.v2_owned_row_ids == ("tasks",)


def test_tasks_module_definition_uses_generated_contract_binding() -> None:
    definition = subject.builtin_tasks_http_routes_definition_v2()

    assert definition.module_ref == subject.TASKS_HTTP_ROUTES_MODULE_V2
    assert definition.contract_digest.startswith("sha256:")
