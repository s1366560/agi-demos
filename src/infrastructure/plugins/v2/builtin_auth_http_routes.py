"""V2-owned production contributions for the builtin authentication HTTP row."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from src.application.schemas.auth import (
    APIKeyResponse,
    ForceChangePasswordResponse,
    Token,
    User as UserSchema,
)
from src.infrastructure.adapters.primary.web.routers.auth import (
    OAuthLoginResponse,
    begin_oauth_authorization,
    create_new_api_key,
    device_code_approve,
    device_code_cancel,
    device_code_request,
    device_code_token,
    force_change_password,
    list_api_keys,
    list_oauth_providers,
    login_for_access_token,
    oauth_callback,
    read_users_me,
    revoke_api_key,
    sign_out,
    update_user_me,
)

from .http_routes import RouteDefinitionV2, RouteTableBuilderV2
from .route_effects import ROUTE_TABLE_BUILDER_INJECT_V2
from .runtime import (
    ContextV2,
    PluginDefinitionV2,
    RuntimeV2Error,
    generated_contract_digest_v2,
)

AUTH_HTTP_ROUTES_ENTRY_V2 = "builtin-auth-http-routes"
AUTH_HTTP_ROUTES_MODULE_V2 = "builtin://memstack/http/auth-routes"
AUTH_HTTP_ROUTES_ROW_V2 = "auth"


def _auth_route_v2(
    *,
    path: str,
    methods: tuple[str, ...],
    endpoint: Callable[..., Any],
    name: str,
    response_model: object | None,
    status_code: int | None = None,
) -> RouteDefinitionV2:
    return RouteDefinitionV2(
        owner_entry_id=AUTH_HTTP_ROUTES_ENTRY_V2,
        path=path,
        methods=methods,
        endpoint=endpoint,
        name=name,
        tags=("Authentication",),
        status_code=status_code,
        response_model=response_model,
        replaces_builtin_row_id=AUTH_HTTP_ROUTES_ROW_V2,
    )


def auth_route_definitions_v2() -> tuple[RouteDefinitionV2, ...]:
    """Return the complete, explicitly claimed ``auth`` inventory row."""
    mapping: tuple[
        tuple[str, tuple[str, ...], Callable[..., Any], str, object | None, int | None],
        ...,
    ] = (
        (
            "/api/v1/auth/token",
            ("POST",),
            login_for_access_token,
            "login_for_access_token",
            Token,
            None,
        ),
        (
            "/api/v1/auth/signout",
            ("POST",),
            sign_out,
            "sign_out",
            dict[str, bool],
            None,
        ),
        (
            "/api/v1/auth/oauth/providers",
            ("GET",),
            list_oauth_providers,
            "list_oauth_providers",
            dict[str, list[dict[str, str]]],
            None,
        ),
        (
            "/api/v1/auth/oauth/{provider}/authorize",
            ("POST",),
            begin_oauth_authorization,
            "begin_oauth_authorization",
            dict[str, str | int],
            None,
        ),
        (
            "/api/v1/auth/oauth/{provider}/callback",
            ("POST",),
            oauth_callback,
            "oauth_callback",
            OAuthLoginResponse,
            None,
        ),
        (
            "/api/v1/auth/force-change-password",
            ("POST",),
            force_change_password,
            "force_change_password",
            ForceChangePasswordResponse,
            None,
        ),
        (
            "/api/v1/auth/keys",
            ("POST",),
            create_new_api_key,
            "create_new_api_key",
            APIKeyResponse,
            None,
        ),
        (
            "/api/v1/auth/keys",
            ("GET",),
            list_api_keys,
            "list_api_keys",
            list[APIKeyResponse],
            None,
        ),
        (
            "/api/v1/auth/keys/{key_id}",
            ("DELETE",),
            revoke_api_key,
            "revoke_api_key",
            None,
            204,
        ),
        (
            "/api/v1/auth/me",
            ("GET",),
            read_users_me,
            "read_users_me",
            UserSchema,
            None,
        ),
        (
            "/api/v1/users/me",
            ("GET",),
            read_users_me,
            "read_users_me",
            UserSchema,
            None,
        ),
        (
            "/api/v1/users/me",
            ("PUT",),
            update_user_me,
            "update_user_me",
            UserSchema,
            None,
        ),
        (
            "/api/v1/auth/device/code",
            ("POST",),
            device_code_request,
            "device_code_request",
            dict[str, Any],
            None,
        ),
        (
            "/api/v1/auth/device/approve",
            ("POST",),
            device_code_approve,
            "device_code_approve",
            dict[str, Any],
            None,
        ),
        (
            "/api/v1/auth/device/token",
            ("POST",),
            device_code_token,
            "device_code_token",
            dict[str, Any],
            None,
        ),
        (
            "/api/v1/auth/device/cancel",
            ("POST",),
            device_code_cancel,
            "device_code_cancel",
            dict[str, bool],
            None,
        ),
    )
    return tuple(
        _auth_route_v2(
            path=path,
            methods=methods,
            endpoint=endpoint,
            name=name,
            response_model=response_model,
            status_code=status_code,
        )
        for path, methods, endpoint, name, response_model, status_code in mapping
    )


def builtin_auth_http_routes_definition_v2() -> PluginDefinitionV2:
    """Register authentication routes as reversible effects of one V2 Fiber."""
    definitions = auth_route_definitions_v2()

    async def apply(context: ContextV2, _config: Mapping[str, Any]) -> None:
        builder = context.require(ROUTE_TABLE_BUILDER_INJECT_V2)
        if not isinstance(builder, RouteTableBuilderV2):
            raise RuntimeV2Error(
                "invalid_route_table_builder",
                "route_table inject is not a protocol v2 route table builder",
            )

        async def setup() -> tuple[Callable[[], Awaitable[None]], ...]:
            disposers: list[Callable[[], Awaitable[None]]] = []
            try:
                for definition in definitions:
                    disposers.append(builder.contribute(definition))
            except Exception:
                for dispose in reversed(disposers):
                    await dispose()
                raise
            return tuple(disposers)

        await context.effect(setup, label=AUTH_HTTP_ROUTES_ENTRY_V2)

    return PluginDefinitionV2(
        module_ref=AUTH_HTTP_ROUTES_MODULE_V2,
        contract_digest=generated_contract_digest_v2(AUTH_HTTP_ROUTES_MODULE_V2),
        apply=apply,
    )


__all__ = [
    "AUTH_HTTP_ROUTES_ENTRY_V2",
    "AUTH_HTTP_ROUTES_MODULE_V2",
    "AUTH_HTTP_ROUTES_ROW_V2",
    "auth_route_definitions_v2",
    "builtin_auth_http_routes_definition_v2",
]
