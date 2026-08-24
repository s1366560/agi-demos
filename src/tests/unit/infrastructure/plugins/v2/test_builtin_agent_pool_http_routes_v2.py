"""Production V2 ownership tests for Agent Pool HTTP rows."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

import pytest

from src.configuration.workspace_core import get_workspace_core_settings
from src.domain.model.plugins.runtime import PluginGenerationDescriptorV2
from src.infrastructure.plugins.v2 import builtin_agent_pool_http_routes as subject
from src.infrastructure.plugins.v2.builtin_http_routes import build_builtin_route_graph_v2
from src.infrastructure.plugins.v2.http_routes import RouteDefinitionV2, RouteTableBuilderV2
from src.infrastructure.plugins.v2.route_effects import ROUTE_TABLE_BUILDER_INJECT_V2

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from src.infrastructure.plugins.v2.runtime import ContextV2

pytestmark = pytest.mark.unit


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


def test_agent_pool_rows_are_complete_explicit_v2_contributions() -> None:
    definitions = subject.agent_pool_route_definitions_v2()

    assert tuple(
        (definition.replaces_builtin_row_id, definition.path, definition.methods, definition.name)
        for definition in definitions
    ) == (
        ("create-pool", "/api/v1/admin/pool/status", ("GET",), "_get_pool_status"),
        ("create-pool", "/api/v1/admin/pool/instances", ("GET",), "_list_instances"),
        (
            "create-pool",
            "/api/v1/admin/pool/instances/{instance_key}",
            ("GET",),
            "_get_instance",
        ),
        (
            "create-pool",
            "/api/v1/admin/pool/instances/{instance_key}/pause",
            ("POST",),
            "_pause_instance",
        ),
        (
            "create-pool",
            "/api/v1/admin/pool/instances/{instance_key}/resume",
            ("POST",),
            "_resume_instance",
        ),
        (
            "create-pool",
            "/api/v1/admin/pool/instances/{instance_key}",
            ("DELETE",),
            "_terminate_instance",
        ),
        (
            "create-pool",
            "/api/v1/admin/pool/projects/{project_id}/tier",
            ("POST",),
            "_set_project_tier",
        ),
        (
            "create-pool",
            "/api/v1/admin/pool/projects/{project_id}/tier",
            ("GET",),
            "_get_project_tier",
        ),
        ("create-pool", "/api/v1/admin/pool/metrics", ("GET",), "_get_metrics_json"),
        (
            "create-pool",
            "/api/v1/admin/pool/metrics/prometheus",
            ("GET",),
            "_get_metrics_prometheus",
        ),
        (
            "create-project-pool",
            "/api/v1/tenants/{tenant_id}/projects/{project_id}/pool/instances/{agent_mode}",
            ("GET",),
            "_get_project_pool_instance",
        ),
        (
            "create-project-pool",
            "/api/v1/tenants/{tenant_id}/projects/{project_id}/pool/instances/{agent_mode}/pause",
            ("POST",),
            "_pause_project_pool_instance",
        ),
        (
            "create-project-pool",
            "/api/v1/tenants/{tenant_id}/projects/{project_id}/pool/instances/{agent_mode}/resume",
            ("POST",),
            "_resume_project_pool_instance",
        ),
        (
            "create-project-pool",
            "/api/v1/tenants/{tenant_id}/projects/{project_id}/pool/instances/{agent_mode}",
            ("DELETE",),
            "_terminate_project_pool_instance",
        ),
    )
    assert {definition.owner_entry_id for definition in definitions} == {
        subject.AGENT_POOL_HTTP_ROUTES_ENTRY_V2
    }


def test_agent_pool_rows_preserve_route_order_and_openapi() -> None:
    descriptor = PluginGenerationDescriptorV2(
        profile_id="agent-pool-route-parity",
        generation=1,
        digest="0" * 64,
    )
    claimed = build_builtin_route_graph_v2(
        workspace_core_settings=get_workspace_core_settings(),
        route_definitions=subject.agent_pool_route_definitions_v2(),
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
    assert claimed.v2_owned_row_ids == ("create-pool", "create-project-pool")


def test_agent_pool_module_definition_uses_generated_contract_binding() -> None:
    definition = subject.builtin_agent_pool_http_routes_definition_v2()

    assert definition.module_ref == subject.AGENT_POOL_HTTP_ROUTES_MODULE_V2
    assert definition.contract_digest.startswith("sha256:")


async def test_agent_pool_route_effect_teardown_is_lifo() -> None:
    builder = _RecordingBuilder()
    context = _FakeContext(builder, teardown=True)
    expected = [definition.name for definition in subject.agent_pool_route_definitions_v2()]

    await subject.builtin_agent_pool_http_routes_definition_v2().apply(
        cast("ContextV2", context),
        {},
    )

    assert builder.registered == expected
    assert builder.disposed == list(reversed(expected))
    assert context.required_services == [ROUTE_TABLE_BUILDER_INJECT_V2]
    assert context.effect_labels == [subject.AGENT_POOL_HTTP_ROUTES_ENTRY_V2]


async def test_agent_pool_route_partial_setup_cleans_up() -> None:
    builder = _RecordingBuilder(fail_after=4)
    context = _FakeContext(builder, teardown=False)
    expected = [definition.name for definition in subject.agent_pool_route_definitions_v2()[:4]]

    with pytest.raises(RuntimeError, match="planned contribution failure"):
        await subject.builtin_agent_pool_http_routes_definition_v2().apply(
            cast("ContextV2", context),
            {},
        )

    assert builder.registered == expected
    assert builder.disposed == list(reversed(expected))
