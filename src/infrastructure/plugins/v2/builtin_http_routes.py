"""Build the complete builtin HTTP/WS surface as a private v2 route generation."""

from __future__ import annotations

from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from fastapi import FastAPI
from starlette.routing import BaseRoute

from .http_routes import RouteContributionV2, RouteTableV2, install_route_definitions_v2
from .runtime import RuntimeV2Error

_ROOT_PREVIEW_CATCH_ALL = "/{path:path}"
REQUIRED_V2_BUILTIN_ROUTE_ROW_IDS = frozenset(
    {
        "admin-dlq",
        "acp",
        "agent",
        "ai-tools",
        "artifacts",
        "attachments-upload",
        "audit",
        "auth",
        "background-tasks",
        "billing",
        "clusters",
        "channels",
        "create-pool",
        "create-project-pool",
        "cron",
        "data-export",
        "deploy",
        "episodes",
        "events",
        "genes",
        "enhanced-search",
        "enhanced-search-memory",
        "engines",
        "graph",
        "graph-stores",
        "invitations",
        "invitations-public",
        "instance-channels",
        "instance-files",
        "instance-templates",
        "instances",
        "llm-providers",
        "maintenance",
        "memories",
        "mcp",
        "notifications",
        "observability",
        "platform-plugins",
        "plugin-marketplace",
        "project-my-work",
        "project-sandbox",
        "project-sandbox-preview",
        "projects",
        "recall",
        "reflection",
        "sandbox",
        "schema",
        "security-ws",
        "shares",
        "skills",
        "retrieval-stores",
        "smtp-config",
        "subagents",
        "system",
        "support",
        "support-2",
        "task-session",
        "tasks",
        "terminal",
        "tenants",
        "tenant-skill-configs",
        "tenant-webhooks",
        "trust",
        "trust-workspace",
        "tunnel",
        "voice-websocket",
        "websocket",
        "webhooks",
        "workspace-core",
        "workspace-core-runtime",
        "workspace-core-static",
    }
)


@dataclass(frozen=True, kw_only=True)
class BuiltinRouteGraphV2:
    table: RouteTableV2
    mounted_row_ids: tuple[str, ...]
    static_mounted_row_ids: tuple[str, ...]
    v2_owned_row_ids: tuple[str, ...]
    route_signatures: tuple[tuple[str, str, tuple[str, ...]], ...]


def build_builtin_route_graph_v2(
    *,
    workspace_core_settings: object,
    route_definitions: Sequence[RouteContributionV2] = (),
    required_v2_row_ids: Collection[str] = (),
    dependency_overrides: Mapping[Callable[..., Any], Callable[..., Any]] | None = None,
) -> BuiltinRouteGraphV2:
    """Build one private graph exclusively from the generation's V2 contributions."""
    _ = workspace_core_settings
    private_app = FastAPI(
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        title="MemStack Builtin Routes V2",
    )
    private_app.dependency_overrides.update(dict(dependency_overrides or {}))
    definitions = tuple(route_definitions)
    row_owners = _builtin_row_owners_v2(definitions)
    missing_required = sorted(set(required_v2_row_ids) - set(row_owners))
    if missing_required:
        raise RuntimeV2Error(
            "required_route_contribution_missing",
            "required V2 route contributions are missing: " + ", ".join(missing_required),
        )
    ordered_definitions = _definitions_before_root_catch_all_v2(definitions)
    install_route_definitions_v2(private_app, ordered_definitions)
    mounted = _ordered_builtin_row_ids_v2(ordered_definitions)
    return BuiltinRouteGraphV2(
        table=RouteTableV2.from_fastapi_graph(
            private_app,
            definitions=ordered_definitions,
        ),
        mounted_row_ids=mounted,
        static_mounted_row_ids=(),
        v2_owned_row_ids=mounted,
        route_signatures=route_signatures_v2(private_app.router.routes),
    )


def _builtin_row_owners_v2(
    definitions: Sequence[RouteContributionV2],
) -> dict[str, str]:
    owners: dict[str, str] = {}
    for definition in definitions:
        row_id = definition.replaces_builtin_row_id
        if row_id is None:
            continue
        existing_owner = owners.setdefault(row_id, definition.owner_entry_id)
        if existing_owner != definition.owner_entry_id:
            raise RuntimeV2Error(
                "route_row_owner_conflict",
                f"V2 route row {row_id} must have exactly one owner",
            )
    return owners


def _definitions_before_root_catch_all_v2(
    definitions: Sequence[RouteContributionV2],
) -> tuple[RouteContributionV2, ...]:
    """Keep every declared route reachable ahead of the host-preview fallback."""
    regular = tuple(
        definition for definition in definitions if definition.path != _ROOT_PREVIEW_CATCH_ALL
    )
    catch_all = tuple(
        definition for definition in definitions if definition.path == _ROOT_PREVIEW_CATCH_ALL
    )
    return (*regular, *catch_all)


def _ordered_builtin_row_ids_v2(
    definitions: Sequence[RouteContributionV2],
) -> tuple[str, ...]:
    seen: set[str] = set()
    ordered: list[str] = []
    for definition in definitions:
        row_id = definition.replaces_builtin_row_id
        if row_id is None or row_id in seen:
            continue
        seen.add(row_id)
        ordered.append(row_id)
    return tuple(ordered)


def route_signatures_v2(
    routes: list[BaseRoute],
) -> tuple[tuple[str, str, tuple[str, ...]], ...]:
    """Return ordered structural route signatures for parity checks."""
    signatures: list[tuple[str, str, tuple[str, ...]]] = []
    for route in routes:
        path = getattr(route, "path", None)
        if not isinstance(path, str):
            continue
        name = str(getattr(route, "name", ""))
        raw_methods: Any = getattr(route, "methods", None)
        methods = tuple(sorted(str(method) for method in raw_methods)) if raw_methods else ()
        signatures.append((path, name, methods))
    return tuple(signatures)


__all__ = [
    "REQUIRED_V2_BUILTIN_ROUTE_ROW_IDS",
    "BuiltinRouteGraphV2",
    "build_builtin_route_graph_v2",
    "route_signatures_v2",
]
