"""Production V2 ownership tests for the builtin LLM providers HTTP row."""

from __future__ import annotations

from typing import Any

import pytest

from src.configuration.workspace_core import get_workspace_core_settings
from src.domain.llm_providers.models import (
    ProviderConfigResponse,
    ProviderHealth,
    ProviderTypeDescriptor,
    ProviderValidationResponse,
    TenantProviderMapping,
)
from src.domain.model.plugins.runtime import PluginGenerationDescriptorV2
from src.infrastructure.plugins.v2 import builtin_llm_providers_http_routes as subject
from src.infrastructure.plugins.v2.builtin_http_routes import build_builtin_route_graph_v2

pytestmark = pytest.mark.unit


def test_llm_providers_row_is_a_complete_explicit_v2_contribution() -> None:
    definitions = subject.llm_providers_route_definitions_v2()
    prefix = "/api/v1/llm-providers"

    assert tuple(
        (
            definition.path,
            definition.methods,
            definition.name,
            definition.response_model,
            definition.status_code,
        )
        for definition in definitions
    ) == (
        (f"{prefix}/", ("POST",), "create_provider", ProviderConfigResponse, 201),
        (f"{prefix}/", ("GET",), "list_providers", list[ProviderConfigResponse], None),
        (f"{prefix}/types", ("GET",), "list_provider_types", list[ProviderTypeDescriptor], None),
        (f"{prefix}/models/catalog", ("GET",), "list_catalog_models", dict[str, Any], None),
        (
            f"{prefix}/models/catalog/search",
            ("GET",),
            "search_catalog_models",
            dict[str, Any],
            None,
        ),
        (
            f"{prefix}/models/catalog/refresh",
            ("POST",),
            "refresh_catalog_models",
            dict[str, Any],
            None,
        ),
        (
            f"{prefix}/models/{{provider_type}}",
            ("GET",),
            "list_models_for_provider_type",
            dict[str, Any],
            None,
        ),
        (f"{prefix}/env-detection", ("GET",), "detect_env_providers", dict[str, Any], None),
        (
            f"{prefix}/{{provider_id}}",
            ("GET",),
            "get_provider",
            ProviderConfigResponse,
            None,
        ),
        (
            f"{prefix}/{{provider_id}}",
            ("PUT",),
            "update_provider",
            ProviderConfigResponse,
            None,
        ),
        (f"{prefix}/{{provider_id}}", ("DELETE",), "delete_provider", None, 204),
        (
            f"{prefix}/test-connection",
            ("POST",),
            "test_provider_connection",
            ProviderValidationResponse,
            None,
        ),
        (
            f"{prefix}/{{provider_id}}/health-check",
            ("POST",),
            "check_provider_health",
            ProviderValidationResponse,
            None,
        ),
        (
            f"{prefix}/{{provider_id}}/health",
            ("GET",),
            "get_provider_health",
            ProviderHealth,
            None,
        ),
        (
            f"{prefix}/tenants/{{tenant_id}}/assignments",
            ("GET",),
            "list_tenant_assignments",
            list[TenantProviderMapping],
            None,
        ),
        (
            f"{prefix}/tenants/{{tenant_id}}/providers/{{provider_id}}",
            ("POST",),
            "assign_provider_to_tenant",
            dict[str, Any],
            None,
        ),
        (
            f"{prefix}/tenants/{{tenant_id}}/provider",
            ("GET",),
            "get_tenant_provider",
            ProviderConfigResponse,
            None,
        ),
        (
            f"{prefix}/tenants/{{tenant_id}}/providers/{{provider_id}}",
            ("DELETE",),
            "unassign_provider_from_tenant",
            dict[str, Any],
            None,
        ),
        (
            f"{prefix}/{{provider_id}}/usage",
            ("GET",),
            "get_provider_usage",
            dict[str, Any],
            None,
        ),
        (f"{prefix}/system/status", ("GET",), "get_system_resilience_status", dict[str, Any], None),
        (
            f"{prefix}/system/reset-circuit-breaker/{{provider_type}}",
            ("POST",),
            "reset_circuit_breaker",
            dict[str, Any],
            None,
        ),
    )
    assert {definition.tags for definition in definitions} == {("LLM Providers",)}
    assert {definition.owner_entry_id for definition in definitions} == {
        subject.LLM_PROVIDERS_HTTP_ROUTES_ENTRY_V2
    }
    assert {definition.replaces_builtin_row_id for definition in definitions} == {"llm-providers"}


def test_llm_providers_row_preserves_route_order_and_openapi() -> None:
    descriptor = PluginGenerationDescriptorV2(
        profile_id="llm-providers-route-parity",
        generation=1,
        digest="0" * 64,
    )
    baseline = build_builtin_route_graph_v2(
        workspace_core_settings=get_workspace_core_settings(),
    )
    claimed = build_builtin_route_graph_v2(
        workspace_core_settings=get_workspace_core_settings(),
        route_definitions=subject.llm_providers_route_definitions_v2(),
    )

    assert claimed.route_signatures == baseline.route_signatures
    assert (
        claimed.table.openapi_snapshot(descriptor).schema
        == baseline.table.openapi_snapshot(descriptor).schema
    )
    assert claimed.v2_owned_row_ids == ("llm-providers",)


def test_llm_providers_module_definition_uses_generated_contract_binding() -> None:
    definition = subject.builtin_llm_providers_http_routes_definition_v2()

    assert definition.module_ref == subject.LLM_PROVIDERS_HTTP_ROUTES_MODULE_V2
    assert definition.contract_digest.startswith("sha256:")
