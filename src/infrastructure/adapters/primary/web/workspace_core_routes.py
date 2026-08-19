"""Atomic registration for the Workspace HTTP compatibility surface."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any, cast

from fastapi import APIRouter, FastAPI, Request
from fastapi.routing import APIRoute, request_response
from pydantic import BaseModel
from sqlalchemy import select
from starlette.responses import JSONResponse, Response, StreamingResponse

from src.infrastructure.adapters.primary.web.dependencies import (
    get_current_actor,
    get_current_user,
    verify_api_key_dependency,
)
from src.infrastructure.adapters.primary.web.routers import (
    blackboard,
    cyber_genes,
    cyber_objectives,
    topology,
    workspace_agent_policy,
    workspace_autonomy,
    workspace_chat,
    workspace_context,
    workspace_plans,
    workspace_tasks,
    workspaces,
)
from src.infrastructure.adapters.primary.web.workspace_authority import (
    workspace_core_unavailable_detail,
)
from src.infrastructure.adapters.secondary.common.base_repository import refresh_select_statement
from src.infrastructure.adapters.secondary.persistence.database import async_session_factory
from src.infrastructure.adapters.secondary.persistence.models import UserProject
from src.infrastructure.workspace_core.client import (
    WorkspaceCoreClient,
    WorkspaceCoreClientError,
)

logger = logging.getLogger(__name__)


class WorkspaceCoreRoutesUnavailableError(RuntimeError):
    """Raised when the selected authority has no complete compatibility routes."""


_LEGACY_STATIC_ROUTERS: tuple[APIRouter, ...] = (
    workspace_context.router,
    workspace_agent_policy.legacy_router,
)

_LEGACY_ROUTERS: tuple[APIRouter, ...] = (
    workspace_autonomy.router,
    workspace_tasks.router,
    workspace_plans.router,
    workspace_agent_policy.router,
    workspaces.router,
    blackboard.router,
    workspace_chat.router,
    topology.router,
    cyber_objectives.router,
    cyber_genes.router,
)

_PROXY_REQUEST_PARAM = "__workspace_core_request"
_PROXY_AUTH_DEPENDENCIES = frozenset(
    {
        get_current_actor,
        get_current_user,
        verify_api_key_dependency,
    }
)
_REQUEST_HEADER_ALLOWLIST = frozenset(
    {
        "accept",
        "accept-language",
        "content-type",
        "idempotency-key",
        "if-match",
        "if-none-match",
        "last-event-id",
        "range",
        "traceparent",
        "tracestate",
        "x-correlation-id",
        "x-request-id",
    }
)
_RESPONSE_HEADER_BLOCKLIST = frozenset(
    {
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailer",
        "transfer-encoding",
        "upgrade",
    }
)
_CONTEXT_HEADER_NAMES = {
    "tenant_id": "X-MemStack-Tenant-ID",
    "project_id": "X-MemStack-Project-ID",
    "workspace_id": "X-MemStack-Workspace-ID",
    "conversation_id": "X-MemStack-Conversation-ID",
    "task_id": "X-MemStack-Task-ID",
    "plan_node_id": "X-MemStack-Plan-Node-ID",
}


def _register_avernet_proxy_routes(
    app: FastAPI,
    source_routers: tuple[APIRouter, ...],
) -> None:
    for source_router in source_routers:
        for source_route in source_router.routes:
            if not isinstance(source_route, APIRoute):
                continue
            app.router.routes.append(_clone_as_avernet_proxy(source_route, app))


def _clone_as_avernet_proxy(source: APIRoute, app: FastAPI) -> APIRoute:
    proxy_route = APIRoute(
        source.path,
        source.endpoint,
        response_model=source.response_model,
        status_code=source.status_code,
        tags=source.tags,
        dependencies=source.dependencies,
        summary=source.summary,
        description=source.description,
        response_description=source.response_description,
        responses=source.responses,
        deprecated=source.deprecated,
        name=source.name,
        methods=source.methods,
        operation_id=source.operation_id,
        response_model_include=source.response_model_include,
        response_model_exclude=source.response_model_exclude,
        response_model_by_alias=source.response_model_by_alias,
        response_model_exclude_unset=source.response_model_exclude_unset,
        response_model_exclude_defaults=source.response_model_exclude_defaults,
        response_model_exclude_none=source.response_model_exclude_none,
        include_in_schema=source.include_in_schema,
        response_class=source.response_class,
        dependency_overrides_provider=app,
        callbacks=source.callbacks,
        openapi_extra=source.openapi_extra,
        generate_unique_id_function=source.generate_unique_id_function,
    )

    async def proxy_endpoint(**endpoint_values: Any) -> Response:  # noqa: ANN401
        request = cast(Request, endpoint_values[_PROXY_REQUEST_PARAM])
        return await _proxy_workspace_request(request, endpoint_values)

    proxy_endpoint.__name__ = f"avernet_proxy_{source.name}"
    proxy_endpoint.__qualname__ = proxy_endpoint.__name__
    cast(Any, proxy_endpoint).__workspace_contract_module__ = source.endpoint.__module__
    proxy_route.endpoint = proxy_endpoint
    proxy_route.dependant.call = proxy_endpoint
    proxy_route.dependant.request_param_name = _PROXY_REQUEST_PARAM
    proxy_route.dependant.dependencies = [
        dependency
        for dependency in proxy_route.dependant.dependencies
        if dependency.call in _PROXY_AUTH_DEPENDENCIES
    ]
    proxy_route.dependant.body_params.clear()
    openapi_body_field = proxy_route.body_field
    proxy_route.body_field = None
    proxy_route.app = request_response(proxy_route.get_route_handler())
    proxy_route.body_field = openapi_body_field
    return proxy_route


async def _proxy_workspace_request(
    request: Request,
    endpoint_values: Mapping[str, Any],
) -> Response:
    client = getattr(request.app.state, "workspace_core_client", None)
    if not isinstance(client, WorkspaceCoreClient):
        return _workspace_core_unavailable()

    headers = _proxy_request_headers(request, endpoint_values)
    membership_header = await _project_membership_role_header(request, endpoint_values)
    if membership_header is not None:
        headers.append(membership_header)

    try:
        upstream = await client.proxy_request(
            method=request.method,
            path=request.url.path,
            query=cast(bytes, request.scope.get("query_string", b"")),
            body=request.stream(),
            headers=headers,
        )
    except WorkspaceCoreClientError:
        logger.warning(
            "Workspace Core compatibility request failed",
            extra={"method": request.method, "path": request.url.path},
        )
        return _workspace_core_unavailable()

    response_headers = {
        name: value
        for name, value in upstream.headers.items()
        if name.lower() not in _RESPONSE_HEADER_BLOCKLIST
    }
    return StreamingResponse(
        content=upstream.aiter_raw(),
        status_code=upstream.status_code,
        headers=response_headers,
    )


_PROJECT_CREATE_PATH_SUFFIX = "/workspaces"
_MEMBERSHIP_ROLE_HEADER = "x-memstack-project-membership-role"
_MEMBERSHIP_ROLES = frozenset({"owner", "admin", "editor", "member", "viewer"})


async def _project_membership_role_header(
    request: Request,
    endpoint_values: Mapping[str, Any],
) -> tuple[str, str] | None:
    """Vouch the caller's project membership role to Workspace Core.

    Core authorizes workspace creation against its mirrored
    ``project_principal_memberships`` table, which the offline migration only
    backfills once. Attaching the caller's ``user_projects`` role on create
    requests lets Core upsert the mirror row lazily, so workspaces can be
    created in projects provisioned after the migration ran.
    """
    if request.method != "POST":
        return None
    if not request.url.path.rstrip("/").endswith(_PROJECT_CREATE_PATH_SUFFIX):
        return None
    context_values = _workspace_context_values(request, endpoint_values)
    project_id = context_values.get("project_id")
    current_user = endpoint_values.get("current_user")
    api_key = endpoint_values.get("api_key")
    user_id = getattr(current_user, "id", None) or getattr(api_key, "user_id", None)
    if not project_id or user_id is None:
        return None
    async with async_session_factory() as session:
        result = await session.execute(
            refresh_select_statement(
                select(UserProject.role).where(
                    UserProject.user_id == str(user_id),
                    UserProject.project_id == project_id,
                )
            )
        )
        role = result.scalar_one_or_none()
    if role is None:
        return None
    return (_MEMBERSHIP_ROLE_HEADER, role if role in _MEMBERSHIP_ROLES else "member")


def _proxy_request_headers(
    request: Request,
    endpoint_values: Mapping[str, Any],
) -> list[tuple[str, str]]:
    headers = [
        (name, value)
        for name, value in request.headers.items()
        if name.lower() in _REQUEST_HEADER_ALLOWLIST
    ]
    user_authorization = request.headers.get("authorization")
    if user_authorization:
        headers.append(("X-MemStack-User-Authorization", user_authorization))

    context_values = _workspace_context_values(request, endpoint_values)
    headers.extend((_CONTEXT_HEADER_NAMES[name], value) for name, value in context_values.items())
    current_user = endpoint_values.get("current_user")
    api_key = endpoint_values.get("api_key")
    user_id = getattr(current_user, "id", None) or getattr(api_key, "user_id", None)
    if user_id is not None:
        headers.append(("X-MemStack-User-ID", str(user_id)))
    user_email = getattr(current_user, "email", None)
    if isinstance(user_email, str) and user_email.strip():
        headers.append(("X-MemStack-User-Email", user_email))
    api_key_id = getattr(api_key, "id", None)
    if api_key_id is not None:
        headers.append(("X-MemStack-API-Key-ID", str(api_key_id)))
    if current_user is not None:
        headers.append(
            (
                "X-MemStack-User-Is-Superuser",
                "true" if bool(getattr(current_user, "is_superuser", False)) else "false",
            )
        )
    current_actor = endpoint_values.get("current_actor")
    actor_type = getattr(current_actor, "kind", None)
    actor_id = getattr(current_actor, "id", None)
    if actor_type in {"user", "agent"} and isinstance(actor_id, str) and actor_id:
        headers.extend(
            [
                ("X-MemStack-Actor-Type", actor_type),
                ("X-MemStack-Actor-ID", actor_id),
            ]
        )
    return headers


def _workspace_context_values(
    request: Request,
    endpoint_values: Mapping[str, Any],
) -> dict[str, str]:
    context: dict[str, str] = {}
    model_values = [
        value.model_dump() for value in endpoint_values.values() if isinstance(value, BaseModel)
    ]
    for name in _CONTEXT_HEADER_NAMES:
        value: object | None = endpoint_values.get(name)
        if value is None:
            value = request.path_params.get(name)
        if value is None:
            value = request.query_params.get(name)
        if value is None:
            value = next(
                (model[name] for model in model_values if model.get(name) is not None),
                None,
            )
        if value is not None:
            context[name] = str(value)
    return context


def _workspace_core_unavailable() -> JSONResponse:
    return JSONResponse(
        status_code=503,
        content={"detail": workspace_core_unavailable_detail()},
    )


def register_workspace_core_static_routes(app: FastAPI) -> None:
    """Register static Workspace compatibility routes as Avernet proxies."""
    _register_avernet_proxy_routes(app, _LEGACY_STATIC_ROUTERS)


def register_workspace_core_routes(app: FastAPI) -> None:
    """Register the complete Workspace compatibility surface as Avernet proxies."""
    _register_avernet_proxy_routes(app, _LEGACY_ROUTERS)
