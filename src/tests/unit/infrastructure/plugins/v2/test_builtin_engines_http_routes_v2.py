"""Production V2 ownership tests for the builtin engines HTTP row."""

from __future__ import annotations

from src.configuration.workspace_core import get_workspace_core_settings
from src.domain.model.plugins.runtime import PluginGenerationDescriptorV2
from src.infrastructure.plugins.v2 import builtin_engines_http_routes as subject
from src.infrastructure.plugins.v2.builtin_http_routes import build_builtin_route_graph_v2
from src.infrastructure.plugins.v2.engine_services import EngineCatalogV2, EngineDescriptorV2


def _catalog() -> EngineCatalogV2:
    return EngineCatalogV2(
        engines=(
            EngineDescriptorV2(
                runtime_id="test-runtime",
                display_name="Test Runtime",
                display_description="Runtime from the V2 catalog",
                display_tags=("test",),
                display_powered_by="Test",
                order=1,
                image_registry_key="test",
                default_registry_url="example.invalid/test:latest",
            ),
        )
    )


def test_engines_row_is_a_complete_explicit_v2_contribution() -> None:
    definitions = subject.engines_route_definitions_v2(_catalog())

    assert {
        (method, definition.path) for definition in definitions for method in definition.methods
    } == {("GET", "/api/v1/engines")}
    assert {definition.owner_entry_id for definition in definitions} == {
        subject.ENGINES_HTTP_ROUTES_ENTRY_V2
    }
    assert {definition.replaces_builtin_row_id for definition in definitions} == {"engines"}


def test_engines_row_preserves_route_order_and_openapi() -> None:
    descriptor = PluginGenerationDescriptorV2(
        profile_id="engines-route-parity",
        generation=1,
        digest="0" * 64,
    )
    baseline = build_builtin_route_graph_v2(
        workspace_core_settings=get_workspace_core_settings(),
    )
    claimed = build_builtin_route_graph_v2(
        workspace_core_settings=get_workspace_core_settings(),
        route_definitions=subject.engines_route_definitions_v2(_catalog()),
    )

    assert claimed.route_signatures == baseline.route_signatures
    assert (
        claimed.table.openapi_snapshot(descriptor).schema
        == baseline.table.openapi_snapshot(descriptor).schema
    )
    assert claimed.v2_owned_row_ids == ("engines",)


async def test_engines_handler_reads_only_the_injected_catalog() -> None:
    definition = subject.engines_route_definitions_v2(_catalog())[0]

    assert await definition.endpoint() == [
        {
            "runtime_id": "test-runtime",
            "display_name": "Test Runtime",
            "display_description": "Runtime from the V2 catalog",
            "display_tags": ["test"],
            "display_powered_by": "Test",
            "order": 1,
            "image_registry_key": "test",
            "default_registry_url": "example.invalid/test:latest",
        }
    ]


def test_engines_module_definition_uses_generated_contract_binding() -> None:
    definition = subject.builtin_engines_http_routes_definition_v2()

    assert definition.module_ref == subject.ENGINES_HTTP_ROUTES_MODULE_V2
    assert definition.contract_digest.startswith("sha256:")
