"""Durable HTTP route inventory shadow comparison."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from .rollout_buckets import is_scope_selected, settings_allowlist, settings_percentage
from .shadow_rollout import enqueue_shadow_rollout_event, make_shadow_rollout_event

HTTP_ROUTE_INVENTORY_EVENT = "http.route_inventory"


def record_http_route_inventory_shadow(
    *,
    registry_routes: Mapping[str, Sequence[Any]],
    desired_rows: Sequence[Any],
    settings: object,
) -> bool:
    """Compare legacy plugin route registration with declarative desired state.

    HTTP route parity is a global complete-inventory comparison. The payload
    contains route ownership facts only; handler objects and credentials are
    intentionally absent.
    """
    v2_enabled = bool(getattr(settings, "platform_plugin_http_route_v2", False))
    shadow_enabled = bool(getattr(settings, "platform_plugin_http_route_shadow", False))
    if v2_enabled or not shadow_enabled:
        return False
    if not is_scope_selected(
        capability="http_routes",
        scope_id=None,
        percentage=settings_percentage(
            settings,
            "platform_plugin_http_route_shadow_percent",
        ),
        allowlist=settings_allowlist(settings, "platform_plugin_shadow_scope_allowlist"),
    ):
        return False

    legacy = _legacy_inventory(registry_routes)
    typed = _desired_inventory(desired_rows)
    return enqueue_shadow_rollout_event(
        make_shadow_rollout_event(
            capability="http_routes",
            event_name=HTTP_ROUTE_INVENTORY_EVENT,
            hook_name="route_inventory",
            scope_type="global",
            scope_id="global",
            equal=legacy == typed,
            legacy_payload={"routes": legacy},
            typed_payload={"routes": typed},
        )
    )


def _legacy_inventory(
    registry_routes: Mapping[str, Sequence[Any]],
) -> list[dict[str, str]]:
    routes: list[dict[str, str]] = []
    for plugin_id, plugin_routes in sorted(registry_routes.items()):
        for route in plugin_routes:
            routes.append(
                {
                    "plugin_id": str(plugin_id),
                    "method": _field(route, "method").strip().upper(),
                    "path": _field(route, "path").strip(),
                }
            )
    return sorted(routes, key=_route_sort_key)


def _desired_inventory(rows: Sequence[Any]) -> list[dict[str, str]]:
    routes: list[dict[str, str]] = []
    for row in rows:
        if not bool(row.enabled):
            continue
        routes.append(
            {
                "plugin_id": str(row.plugin_id),
                "method": str(row.method).strip().upper(),
                "path": str(row.path).strip(),
            }
        )
    return sorted(routes, key=_route_sort_key)


def _route_sort_key(route: Mapping[str, str]) -> tuple[str, str, str]:
    return str(route["method"]), str(route["path"]), str(route["plugin_id"])


def _field(route: Any, name: str) -> str:  # noqa: ANN401
    if isinstance(route, Mapping):
        return str(route[name])
    return str(getattr(route, name))
