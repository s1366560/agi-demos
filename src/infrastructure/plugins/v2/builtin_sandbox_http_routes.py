"""V2-owned production contribution for the Sandbox HTTP row."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from starlette.responses import Response, StreamingResponse

from src.infrastructure.adapters.primary.web.routers.sandbox import list_sandboxes_root
from src.infrastructure.adapters.primary.web.routers.sandbox.events import (
    subscribe_sandbox_events,
)
from src.infrastructure.adapters.primary.web.routers.sandbox.lifecycle import (
    check_sandbox_health,
    cleanup_expired,
    create_sandbox,
    get_sandbox,
    list_sandbox_profiles,
    list_sandboxes,
    terminate_sandbox,
)
from src.infrastructure.adapters.primary.web.routers.sandbox.schemas import (
    DesktopStatusResponse,
    DesktopStopResponse,
    HealthCheckResponse,
    ListProfilesResponse,
    ListSandboxesResponse,
    ListToolsResponse,
    SandboxResponse,
    SandboxTokenResponse,
    TerminalStatusResponse,
    TerminalStopResponse,
    ToolCallResponse,
    ValidateTokenResponse,
)
from src.infrastructure.adapters.primary.web.routers.sandbox.services import (
    get_desktop_status,
    get_terminal_status,
    start_desktop,
    start_terminal,
    stop_desktop,
    stop_terminal,
)
from src.infrastructure.adapters.primary.web.routers.sandbox.tokens import (
    generate_sandbox_token,
    revoke_project_tokens,
    validate_sandbox_token,
)
from src.infrastructure.adapters.primary.web.routers.sandbox.tools import (
    call_tool,
    connect_mcp,
    execute_bash,
    list_agent_tools,
    list_tools,
    read_file,
    write_file,
)

from .http_routes import RouteDefinitionV2, RouteTableBuilderV2
from .route_effects import ROUTE_TABLE_BUILDER_INJECT_V2
from .runtime import (
    ContextV2,
    PluginDefinitionV2,
    RuntimeV2Error,
    generated_contract_digest_v2,
)

SANDBOX_HTTP_ROUTES_ENTRY_V2 = "builtin-sandbox-http-routes"
SANDBOX_HTTP_ROUTES_MODULE_V2 = "builtin://memstack/http/sandbox-routes"
SANDBOX_HTTP_ROUTES_ROW_V2 = "sandbox"
_SANDBOX_TAGS_V2 = ("sandbox",)


def _sandbox_route_v2(
    *,
    path: str,
    methods: tuple[str, ...],
    endpoint: Callable[..., Any],
    name: str,
    response_model: object | None,
    response_class: type[Response] | None = None,
    include_in_schema: bool = True,
) -> RouteDefinitionV2:
    return RouteDefinitionV2(
        owner_entry_id=SANDBOX_HTTP_ROUTES_ENTRY_V2,
        path=path,
        methods=methods,
        endpoint=endpoint,
        name=name,
        tags=_SANDBOX_TAGS_V2,
        response_model=response_model,
        response_class=response_class,
        include_in_schema=include_in_schema,
        replaces_builtin_row_id=SANDBOX_HTTP_ROUTES_ROW_V2,
    )


def sandbox_route_definitions_v2() -> tuple[RouteDefinitionV2, ...]:
    """Return all 26 routes explicitly claimed from the ``sandbox`` inventory row."""
    prefix = "/api/v1/sandbox"
    return (
        _sandbox_route_v2(
            path=f"{prefix}/projects/{{project_id}}/token",
            methods=("POST",),
            endpoint=generate_sandbox_token,
            name="generate_sandbox_token",
            response_model=SandboxTokenResponse,
        ),
        _sandbox_route_v2(
            path=f"{prefix}/token/validate",
            methods=("POST",),
            endpoint=validate_sandbox_token,
            name="validate_sandbox_token",
            response_model=ValidateTokenResponse,
        ),
        _sandbox_route_v2(
            path=f"{prefix}/projects/{{project_id}}/tokens",
            methods=("DELETE",),
            endpoint=revoke_project_tokens,
            name="revoke_project_tokens",
            response_model=dict[str, Any],
        ),
        _sandbox_route_v2(
            path=f"{prefix}/profiles",
            methods=("GET",),
            endpoint=list_sandbox_profiles,
            name="list_sandbox_profiles",
            response_model=ListProfilesResponse,
        ),
        _sandbox_route_v2(
            path=f"{prefix}/{{sandbox_id}}/health",
            methods=("GET",),
            endpoint=check_sandbox_health,
            name="check_sandbox_health",
            response_model=HealthCheckResponse,
        ),
        _sandbox_route_v2(
            path=f"{prefix}/create",
            methods=("POST",),
            endpoint=create_sandbox,
            name="create_sandbox",
            response_model=SandboxResponse,
        ),
        _sandbox_route_v2(
            path=f"{prefix}/list",
            methods=("GET",),
            endpoint=list_sandboxes,
            name="list_sandboxes",
            response_model=ListSandboxesResponse,
        ),
        _sandbox_route_v2(
            path=f"{prefix}/{{sandbox_id}}",
            methods=("GET",),
            endpoint=get_sandbox,
            name="get_sandbox",
            response_model=SandboxResponse,
        ),
        _sandbox_route_v2(
            path=f"{prefix}/{{sandbox_id}}",
            methods=("DELETE",),
            endpoint=terminate_sandbox,
            name="terminate_sandbox",
            response_model=dict[str, Any],
        ),
        _sandbox_route_v2(
            path=f"{prefix}/cleanup",
            methods=("POST",),
            endpoint=cleanup_expired,
            name="cleanup_expired",
            response_model=dict[str, Any],
        ),
        _sandbox_route_v2(
            path=f"{prefix}/{{sandbox_id}}/connect",
            methods=("POST",),
            endpoint=connect_mcp,
            name="connect_mcp",
            response_model=dict[str, Any],
        ),
        _sandbox_route_v2(
            path=f"{prefix}/{{sandbox_id}}/tools",
            methods=("GET",),
            endpoint=list_tools,
            name="list_tools",
            response_model=ListToolsResponse,
        ),
        _sandbox_route_v2(
            path=f"{prefix}/{{sandbox_id}}/tools/agent",
            methods=("GET",),
            endpoint=list_agent_tools,
            name="list_agent_tools",
            response_model=dict[str, Any],
        ),
        _sandbox_route_v2(
            path=f"{prefix}/{{sandbox_id}}/call",
            methods=("POST",),
            endpoint=call_tool,
            name="call_tool",
            response_model=ToolCallResponse,
        ),
        _sandbox_route_v2(
            path=f"{prefix}/{{sandbox_id}}/read",
            methods=("POST",),
            endpoint=read_file,
            name="read_file",
            response_model=dict[str, Any],
        ),
        _sandbox_route_v2(
            path=f"{prefix}/{{sandbox_id}}/write",
            methods=("POST",),
            endpoint=write_file,
            name="write_file",
            response_model=dict[str, Any],
        ),
        _sandbox_route_v2(
            path=f"{prefix}/{{sandbox_id}}/bash",
            methods=("POST",),
            endpoint=execute_bash,
            name="execute_bash",
            response_model=dict[str, Any],
        ),
        _sandbox_route_v2(
            path=f"{prefix}/{{sandbox_id}}/desktop",
            methods=("POST",),
            endpoint=start_desktop,
            name="start_desktop",
            response_model=DesktopStatusResponse,
        ),
        _sandbox_route_v2(
            path=f"{prefix}/{{sandbox_id}}/desktop",
            methods=("DELETE",),
            endpoint=stop_desktop,
            name="stop_desktop",
            response_model=DesktopStopResponse,
        ),
        _sandbox_route_v2(
            path=f"{prefix}/{{sandbox_id}}/desktop",
            methods=("GET",),
            endpoint=get_desktop_status,
            name="get_desktop_status",
            response_model=DesktopStatusResponse,
        ),
        _sandbox_route_v2(
            path=f"{prefix}/{{sandbox_id}}/terminal",
            methods=("POST",),
            endpoint=start_terminal,
            name="start_terminal",
            response_model=TerminalStatusResponse,
        ),
        _sandbox_route_v2(
            path=f"{prefix}/{{sandbox_id}}/terminal",
            methods=("DELETE",),
            endpoint=stop_terminal,
            name="stop_terminal",
            response_model=TerminalStopResponse,
        ),
        _sandbox_route_v2(
            path=f"{prefix}/{{sandbox_id}}/terminal",
            methods=("GET",),
            endpoint=get_terminal_status,
            name="get_terminal_status",
            response_model=TerminalStatusResponse,
        ),
        _sandbox_route_v2(
            path=f"{prefix}/events/{{project_id}}",
            methods=("GET",),
            endpoint=subscribe_sandbox_events,
            name="subscribe_sandbox_events",
            response_model=None,
            response_class=StreamingResponse,
        ),
        _sandbox_route_v2(
            path=f"{prefix}/",
            methods=("GET",),
            endpoint=list_sandboxes_root,
            name="list_sandboxes_root",
            response_model=ListSandboxesResponse,
            include_in_schema=False,
        ),
        _sandbox_route_v2(
            path=prefix,
            methods=("GET",),
            endpoint=list_sandboxes_root,
            name="list_sandboxes_root",
            response_model=ListSandboxesResponse,
            include_in_schema=False,
        ),
    )


def builtin_sandbox_http_routes_definition_v2() -> PluginDefinitionV2:
    """Register the Sandbox row as one reversible V2 effect."""
    definitions = sandbox_route_definitions_v2()

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

        await context.effect(setup, label=SANDBOX_HTTP_ROUTES_ENTRY_V2)

    return PluginDefinitionV2(
        module_ref=SANDBOX_HTTP_ROUTES_MODULE_V2,
        contract_digest=generated_contract_digest_v2(SANDBOX_HTTP_ROUTES_MODULE_V2),
        apply=apply,
    )


__all__ = [
    "SANDBOX_HTTP_ROUTES_ENTRY_V2",
    "SANDBOX_HTTP_ROUTES_MODULE_V2",
    "SANDBOX_HTTP_ROUTES_ROW_V2",
    "builtin_sandbox_http_routes_definition_v2",
    "sandbox_route_definitions_v2",
]
