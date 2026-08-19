"""Mount the builtin FastAPI route surface from the data-driven baseline.

Phase P1 of the full-pluginization roadmap: the hardcoded
``app.include_router(...)`` block in ``main.py`` becomes an inventory-driven
mount. The loader replays exactly the calls recorded in
``config/plugin-profiles/builtin-routes.v1.json`` — same order, same prefixes,
same interleaved registration helpers — so behavior is unchanged by
construction while every row becomes addressable for profile patches.
"""

from __future__ import annotations

import importlib
import json
import logging
import types
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, Protocol, cast

from .route_inventory import INVENTORY_PATH

logger = logging.getLogger(__name__)

__all__ = [
    "RouteLoadError",
    "install_builtin_routes",
    "load_builtin_route_rows",
]


class RouteLoadError(RuntimeError):
    """Raised when a baseline row cannot be resolved or mounted."""


#: Helpers interleaved between include calls; everything else (for example
#: the lifespan-owned ``install_http_route_capabilities``) stays in main.py.
_INTERLEAVED_HELPERS = frozenset(
    {
        "workspace-core-static",
        "workspace-core",
        "workspace-core-runtime",
        "task-session",
    }
)

#: Helpers called with ``(app, workspace_core_settings)`` instead of ``(app)``.
_SETTINGS_HELPERS = frozenset({"workspace-core-runtime"})


def load_builtin_route_rows(inventory_path: Path = INVENTORY_PATH) -> tuple[dict[str, Any], ...]:
    """Read the checked-in baseline rows in registration order."""
    try:
        payload = json.loads(inventory_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise RouteLoadError(f"cannot read route inventory {inventory_path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise RouteLoadError(f"cannot parse route inventory {inventory_path}: {exc}") from exc
    entries = payload.get("entries")
    if not isinstance(entries, list):
        raise RouteLoadError(f"route inventory {inventory_path} has no entries list")
    return tuple(entries)


class _RouteApp(Protocol):
    """Minimal mount surface the loader needs (FastAPI-compatible)."""

    def include_router(self, router: Any, *, prefix: str = "") -> Any:  # noqa: ANN401
        ...


def install_builtin_routes(
    app: _RouteApp,
    *,
    workspace_core_settings: object | None = None,
    inventory_path: Path = INVENTORY_PATH,
    helper_overrides: Mapping[str, Callable[..., object]] | None = None,
) -> tuple[str, ...]:
    """Replay the baseline's route registrations against *app* in order.

    Returns the row ids that were mounted. Helpers outside the interleaved
    set are skipped (they are owned elsewhere, e.g. lifespan startup).
    ``helper_overrides`` substitutes interleaved helper callables, primarily
    for tests and future profile-level patching.
    """
    mounted: list[str] = []
    for entry in load_builtin_route_rows(inventory_path):
        row_id = entry.get("row_id")
        kind = entry.get("kind")
        if kind == "include_router":
            router = _resolve_router(entry)
            prefix = entry.get("prefix")
            if prefix is not None:
                app.include_router(router, prefix=prefix)
            else:
                app.include_router(router)
            mounted.append(cast(str, row_id))
        elif kind == "helper" and row_id in _INTERLEAVED_HELPERS:
            helper = cast(
                Callable[..., object],
                helper_overrides[row_id]
                if helper_overrides and row_id in helper_overrides
                else _resolve_dotted(_require_module(entry)),
            )
            if row_id in _SETTINGS_HELPERS:
                if workspace_core_settings is None:
                    raise RouteLoadError(f"helper {row_id} requires workspace_core_settings")
                helper(app, workspace_core_settings)
            else:
                helper(app)
            mounted.append(cast(str, row_id))
    logger.info(
        "Builtin route rows mounted from baseline: %d rows",
        len(mounted),
    )
    return tuple(mounted)


def _require_module(entry: dict[str, Any]) -> str:
    module = entry.get("module")
    if not isinstance(module, str) or not module:
        raise RouteLoadError(f"route row {entry.get('row_id')} has no resolvable module")
    return module


def _resolve_router(entry: dict[str, Any]) -> object:
    """Resolve one include_router baseline row to a router object."""
    module = _require_module(entry)
    expression = entry.get("expression", "")
    try:
        if expression.endswith("()"):
            factory = cast(Callable[[], object], _resolve_dotted(module))
            return factory()
        if "." in expression:
            attribute = expression.rsplit(".", 1)[1]
            owner = importlib.import_module(module)
            return getattr(owner, attribute)
        resolved = _resolve_dotted(module)
        # `from pkg import router as name` points at a module whose router
        # attribute is the mount target.
        if isinstance(resolved, types.ModuleType):
            return resolved.router
        return resolved
    except (ImportError, AttributeError, TypeError) as exc:
        raise RouteLoadError(
            f"cannot resolve route row {entry.get('row_id')} ({expression}): {exc}"
        ) from exc


def _resolve_dotted(dotted: str) -> object:
    """Resolve a dotted object path, popping trailing attributes until importable."""
    parts = dotted.split(".")
    for cut in range(len(parts), 0, -1):
        module_name = ".".join(parts[:cut])
        try:
            obj: object = importlib.import_module(module_name)
        except ImportError as exc:
            if getattr(exc, "name", None) == module_name:
                continue
            raise
        for attribute in parts[cut:]:
            obj = getattr(obj, attribute)
        return obj
    raise RouteLoadError(f"cannot import any prefix of {dotted}")
