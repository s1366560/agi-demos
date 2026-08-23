"""Production V2 ownership tests for the builtin authentication HTTP row."""

from __future__ import annotations

from typing import Any

import pytest

from src.application.schemas.auth import (
    APIKeyResponse,
    ForceChangePasswordResponse,
    Token,
    User,
)
from src.configuration.workspace_core import get_workspace_core_settings
from src.domain.model.plugins.runtime import PluginGenerationDescriptorV2
from src.infrastructure.adapters.primary.web.routers.auth import OAuthLoginResponse
from src.infrastructure.plugins.v2 import builtin_auth_http_routes as subject
from src.infrastructure.plugins.v2.builtin_http_routes import build_builtin_route_graph_v2

pytestmark = pytest.mark.unit


def test_auth_row_is_a_complete_explicit_v2_contribution() -> None:
    definitions = subject.auth_route_definitions_v2()

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
        ("/api/v1/auth/token", ("POST",), "login_for_access_token", Token, None),
        ("/api/v1/auth/signout", ("POST",), "sign_out", dict[str, bool], None),
        (
            "/api/v1/auth/oauth/providers",
            ("GET",),
            "list_oauth_providers",
            dict[str, list[dict[str, str]]],
            None,
        ),
        (
            "/api/v1/auth/oauth/{provider}/authorize",
            ("POST",),
            "begin_oauth_authorization",
            dict[str, str | int],
            None,
        ),
        (
            "/api/v1/auth/oauth/{provider}/callback",
            ("POST",),
            "oauth_callback",
            OAuthLoginResponse,
            None,
        ),
        (
            "/api/v1/auth/force-change-password",
            ("POST",),
            "force_change_password",
            ForceChangePasswordResponse,
            None,
        ),
        ("/api/v1/auth/keys", ("POST",), "create_new_api_key", APIKeyResponse, None),
        ("/api/v1/auth/keys", ("GET",), "list_api_keys", list[APIKeyResponse], None),
        ("/api/v1/auth/keys/{key_id}", ("DELETE",), "revoke_api_key", None, 204),
        ("/api/v1/auth/me", ("GET",), "read_users_me", User, None),
        ("/api/v1/users/me", ("GET",), "read_users_me", User, None),
        ("/api/v1/users/me", ("PUT",), "update_user_me", User, None),
        ("/api/v1/auth/device/code", ("POST",), "device_code_request", dict[str, Any], None),
        (
            "/api/v1/auth/device/approve",
            ("POST",),
            "device_code_approve",
            dict[str, Any],
            None,
        ),
        ("/api/v1/auth/device/token", ("POST",), "device_code_token", dict[str, Any], None),
        ("/api/v1/auth/device/cancel", ("POST",), "device_code_cancel", dict[str, bool], None),
    )
    assert {definition.tags for definition in definitions} == {("Authentication",)}
    assert {definition.owner_entry_id for definition in definitions} == {
        subject.AUTH_HTTP_ROUTES_ENTRY_V2
    }
    assert {definition.replaces_builtin_row_id for definition in definitions} == {"auth"}


def test_auth_row_preserves_route_order_and_openapi() -> None:
    descriptor = PluginGenerationDescriptorV2(
        profile_id="auth-route-parity",
        generation=1,
        digest="0" * 64,
    )
    baseline = build_builtin_route_graph_v2(
        workspace_core_settings=get_workspace_core_settings(),
    )
    claimed = build_builtin_route_graph_v2(
        workspace_core_settings=get_workspace_core_settings(),
        route_definitions=subject.auth_route_definitions_v2(),
    )

    assert claimed.route_signatures == baseline.route_signatures
    assert (
        claimed.table.openapi_snapshot(descriptor).schema
        == baseline.table.openapi_snapshot(descriptor).schema
    )
    assert claimed.v2_owned_row_ids == ("auth",)


def test_auth_module_definition_uses_generated_contract_binding() -> None:
    definition = subject.builtin_auth_http_routes_definition_v2()

    assert definition.module_ref == subject.AUTH_HTTP_ROUTES_MODULE_V2
    assert definition.contract_digest.startswith("sha256:")
