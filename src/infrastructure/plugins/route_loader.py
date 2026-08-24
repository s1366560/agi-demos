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
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, cast

from fastapi import FastAPI

from .profile import ProfilePatch
from .route_inventory import INVENTORY_PATH
from .v2.builtin_route_contracts import (
    BUILTIN_ROUTE_CONTRACT_CATALOG_PATH_V2,
    BuiltinRouteContractCatalogErrorV2,
    BuiltinRouteContractCatalogV2,
    load_builtin_route_contract_catalog_v2,
)
from .v2.http_routes import RouteContributionV2, install_route_definitions_v2
from .v2.route_registration import (
    RouteRegistrationClassificationV2,
    create_route_contract_app_v2,
    ordered_route_signatures_v2,
    route_openapi_digest_v2,
)

logger = logging.getLogger(__name__)

__all__ = [
    "BuiltinRouteRowOverride",
    "RouteLoadError",
    "RouteRowPatch",
    "install_builtin_routes",
    "load_builtin_route_rows",
    "route_patches_from_profile",
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

#: Profile patch target prefix addressing one builtin route row.
ROUTE_PATCH_TARGET_PREFIX = "route:"

#: Replacement fields a route row patch may carry in its config.
_PATCH_CONFIG_KEYS = frozenset({"module", "expression", "prefix"})


@dataclass(frozen=True)
class RouteRowPatch:
    """Per-row patch to the builtin route surface from a composed profile.

    ``enabled=False`` disables the row entirely; ``module``/``expression``/
    ``prefix`` replace how an ``include_router`` row resolves. Trust
    enforcement (only builtin/signed layers may patch builtin rows) happens
    in the control plane; the loader applies the patches it is given.
    """

    row_id: str
    enabled: bool | None = None
    module: str | None = None
    expression: str | None = None
    prefix: str | None = None


@dataclass(frozen=True)
class BuiltinRouteRowOverride:
    """One explicit, complete HTTP/WebSocket replacement for an inventory row."""

    row_id: str
    owner_entry_id: str
    definitions: tuple[RouteContributionV2, ...]

    def __post_init__(self) -> None:
        if not self.row_id.strip():
            raise ValueError("builtin route override row_id must be non-empty")
        if not self.owner_entry_id.strip():
            raise ValueError("builtin route override owner_entry_id must be non-empty")
        if not self.definitions:
            raise ValueError("builtin route override definitions must be non-empty")
        for definition in self.definitions:
            if definition.owner_entry_id != self.owner_entry_id:
                raise ValueError("builtin route override definitions must have exactly one owner")
            if definition.replaces_builtin_row_id != self.row_id:
                raise ValueError("builtin route override definitions must replace the declared row")
        for method, path in self.route_keys:
            if method != method.upper() or not method.strip():
                raise ValueError("builtin route override methods must use canonical uppercase form")
            if not path.startswith("/"):
                raise ValueError("builtin route override paths must start with /")

    @property
    def route_keys(self) -> frozenset[tuple[str, str]]:
        return frozenset(
            (method.upper(), definition.path)
            for definition in self.definitions
            for method in definition.methods
        )


def route_patches_from_profile(
    patches: tuple[ProfilePatch, ...] | list[ProfilePatch],
) -> dict[str, RouteRowPatch]:
    """Translate composed-profile patches into route row patches.

    A profile patch whose target is ``route:<row_id>`` addresses the builtin
    route row ``<row_id>``: ``enabled: false`` or ``remove: true`` disables
    it, and ``config`` may carry ``module``/``expression``/``prefix``
    replacement fields for ``include_router`` rows.
    """
    resolved: dict[str, RouteRowPatch] = {}
    for patch in patches:
        if not patch.target.startswith(ROUTE_PATCH_TARGET_PREFIX):
            continue
        row_id = patch.target[len(ROUTE_PATCH_TARGET_PREFIX) :]
        if not row_id:
            raise RouteLoadError(f"route patch {patch.target!r} has an empty row id")
        config = patch.config or {}
        unknown = sorted(set(config) - _PATCH_CONFIG_KEYS)
        if unknown:
            raise RouteLoadError(
                f"route patch for {row_id} has unknown config keys: {', '.join(unknown)}"
            )
        enabled: bool | None = patch.enabled
        if patch.remove:
            enabled = False
        resolved[row_id] = RouteRowPatch(
            row_id=row_id,
            enabled=enabled,
            module=_optional_str(config.get("module"), row_id, "module"),
            expression=_optional_str(config.get("expression"), row_id, "expression"),
            prefix=_optional_str(config.get("prefix"), row_id, "prefix"),
        )
    return resolved


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
    route_contract_catalog_path: Path = BUILTIN_ROUTE_CONTRACT_CATALOG_PATH_V2,
    helper_overrides: Mapping[str, Callable[..., object]] | None = None,
    row_patches: Mapping[str, RouteRowPatch] | None = None,
    row_overrides: Mapping[str, BuiltinRouteRowOverride] | None = None,
) -> tuple[str, ...]:
    """Replay the baseline's route registrations against *app* in order.

    Returns the row ids that were mounted. Helpers outside the interleaved
    set are skipped (they are owned elsewhere, e.g. lifespan startup).
    ``helper_overrides`` substitutes interleaved helper callables, primarily
    for tests and future profile-level patching.
    ``row_patches`` applies per-row profile patches: unknown targets are
    rejected, disabled rows are skipped, and replacement fields change how
    an ``include_router`` row resolves.
    ``row_overrides`` installs a complete V2-owned HTTP row at the baseline
    position only when its declared method/path set exactly matches the
    resolved inventory router. Partial ownership fails closed.
    """
    rows = load_builtin_route_rows(inventory_path)
    _validate_route_customizations(
        rows,
        row_patches=row_patches or {},
        row_overrides=row_overrides or {},
    )
    patches = row_patches or {}
    overrides = row_overrides or {}
    helpers = helper_overrides or {}
    route_contract_catalog = _load_route_contract_catalog_v2(
        inventory_path=inventory_path,
        catalog_path=route_contract_catalog_path,
        required=bool(overrides),
    )
    mounted: list[str] = []
    for entry in rows:
        if _mount_builtin_route_row(
            app,
            entry,
            workspace_core_settings=workspace_core_settings,
            helper_overrides=helpers,
            row_patches=patches,
            row_overrides=overrides,
            route_contract_catalog=route_contract_catalog,
        ):
            mounted.append(cast(str, entry["row_id"]))
    logger.info("Builtin route rows mounted from baseline: %d rows", len(mounted))
    return tuple(mounted)


def _validate_route_customizations(
    rows: tuple[dict[str, Any], ...],
    *,
    row_patches: Mapping[str, RouteRowPatch],
    row_overrides: Mapping[str, BuiltinRouteRowOverride],
) -> None:
    known = {entry.get("row_id") for entry in rows}
    for label, candidates in (("patches", row_patches), ("overrides", row_overrides)):
        unknown = sorted(set(candidates) - known)
        if unknown:
            raise RouteLoadError(
                f"route {label} target unknown baseline rows: {', '.join(unknown)}"
            )
    overlap = sorted(set(row_patches) & set(row_overrides))
    if overlap:
        raise RouteLoadError(
            "builtin route rows cannot have both a profile patch and a V2 override: "
            + ", ".join(overlap)
        )
    for key, override in row_overrides.items():
        if key != override.row_id:
            raise RouteLoadError(
                f"route override key {key} does not match declared row {override.row_id}"
            )


def _load_route_contract_catalog_v2(
    *,
    inventory_path: Path,
    catalog_path: Path,
    required: bool,
) -> BuiltinRouteContractCatalogV2 | None:
    if not required:
        return None
    try:
        return load_builtin_route_contract_catalog_v2(
            catalog_path=catalog_path,
            inventory_path=inventory_path,
        )
    except BuiltinRouteContractCatalogErrorV2 as exc:
        raise RouteLoadError(f"V2 route contract catalog rejected: {exc}") from exc


def _mount_builtin_route_row(
    app: _RouteApp,
    entry: dict[str, Any],
    *,
    workspace_core_settings: object | None,
    helper_overrides: Mapping[str, Callable[..., object]],
    row_patches: Mapping[str, RouteRowPatch],
    row_overrides: Mapping[str, BuiltinRouteRowOverride],
    route_contract_catalog: BuiltinRouteContractCatalogV2 | None,
) -> bool:
    row_id = entry.get("row_id")
    if not isinstance(row_id, str) or not row_id:
        raise RouteLoadError("builtin route inventory row_id must be a non-empty string")
    patch = row_patches.get(row_id)
    if patch is not None and patch.enabled is False:
        logger.info("Builtin route row %s disabled by profile patch", row_id)
        return False
    override = row_overrides.get(row_id)
    if override is not None:
        if route_contract_catalog is None:
            raise RouteLoadError("V2 route overrides require a validated route contract catalog")
        _mount_v2_row_override(app, entry, override, route_contract_catalog)
        return True
    if entry.get("kind") == "include_router":
        _mount_inventory_router(app, entry, patch)
        return True
    if entry.get("kind") == "helper" and row_id in _INTERLEAVED_HELPERS:
        _mount_interleaved_helper(
            app,
            entry,
            row_id=row_id,
            workspace_core_settings=workspace_core_settings,
            helper_overrides=helper_overrides,
        )
        return True
    return False


def _mount_v2_row_override(
    app: _RouteApp,
    entry: dict[str, Any],
    override: BuiltinRouteRowOverride,
    catalog: BuiltinRouteContractCatalogV2,
) -> None:
    row_id = override.row_id
    try:
        contract = catalog.runtime_row(row_id)
    except BuiltinRouteContractCatalogErrorV2 as exc:
        raise RouteLoadError(str(exc)) from exc
    expected_identity = (
        entry.get("kind"),
        entry.get("module"),
        entry.get("expression"),
        entry.get("prefix"),
    )
    contract_identity = (
        contract.inventory_kind,
        contract.module,
        contract.expression,
        contract.prefix,
    )
    if contract_identity != expected_identity:
        raise RouteLoadError(f"V2 route contract owner mismatch for row {row_id}")
    if contract.classification is not RouteRegistrationClassificationV2.ROUTES_ONLY:
        raise RouteLoadError(
            f"V2 route override target {row_id} is {contract.classification.value}, not routes-only"
        )

    candidate = create_route_contract_app_v2()
    try:
        install_route_definitions_v2(candidate, override.definitions)
    except Exception as exc:
        raise RouteLoadError(
            f"V2 override for row {row_id} could not materialize: {type(exc).__name__}"
        ) from exc
    actual_signatures = ordered_route_signatures_v2(candidate.router.routes)
    expected_payloads = tuple(signature.to_payload() for signature in contract.ordered_signatures)
    actual_payloads = tuple(signature.to_payload() for signature in actual_signatures)
    if actual_payloads != expected_payloads:
        expected_keys = frozenset(
            (method, signature.path)
            for signature in contract.ordered_signatures
            for method in signature.methods
        )
        missing = sorted(expected_keys - override.route_keys)
        unexpected = sorted(override.route_keys - expected_keys)
        detail = (
            f"V2 override for row {row_id} must replace the complete route key set;"
            f" missing={missing}, unexpected={unexpected}, ordered metadata mismatch"
        )
        raise RouteLoadError(detail)
    actual_openapi_digest = route_openapi_digest_v2(candidate)
    if actual_openapi_digest != contract.openapi_digest:
        raise RouteLoadError(
            f"V2 override for row {row_id} OpenAPI digest mismatch; "
            f"contract={contract.contract_digest}"
        )
    install_route_definitions_v2(cast("FastAPI", app), override.definitions)


def _mount_inventory_router(
    app: _RouteApp,
    entry: dict[str, Any],
    patch: RouteRowPatch | None,
) -> None:
    router = _resolve_router(_patched_entry(entry, patch))
    prefix = patch.prefix if patch is not None and patch.prefix is not None else entry.get("prefix")
    if prefix is not None:
        app.include_router(router, prefix=prefix)
    else:
        app.include_router(router)


def _mount_interleaved_helper(
    app: _RouteApp,
    entry: dict[str, Any],
    *,
    row_id: str,
    workspace_core_settings: object | None,
    helper_overrides: Mapping[str, Callable[..., object]],
) -> None:
    helper = cast(
        Callable[..., object],
        helper_overrides.get(row_id) or _resolve_dotted(_require_module(entry)),
    )
    if row_id not in _SETTINGS_HELPERS:
        _ = helper(app)
        return
    if workspace_core_settings is None:
        raise RouteLoadError(f"helper {row_id} requires workspace_core_settings")
    _ = helper(app, workspace_core_settings)


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


def _patched_entry(entry: dict[str, Any], patch: RouteRowPatch | None) -> dict[str, Any]:
    """Merge replacement fields of a route row patch into a baseline row."""
    if patch is None:
        return entry
    merged = dict(entry)
    if patch.module is not None:
        merged["module"] = patch.module
    if patch.expression is not None:
        merged["expression"] = patch.expression
    return merged


def _optional_str(value: object, row_id: str, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise RouteLoadError(f"route patch for {row_id} has a non-string {field}")
    return value
