"""Generated contract catalog for every frozen builtin HTTP route inventory row."""

from __future__ import annotations

import hashlib
import importlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from types import MappingProxyType, ModuleType
from typing import Any, cast

import rfc8785

from src.infrastructure.plugins.route_inventory import INVENTORY_PATH

from .route_catalog_worker import RouteCatalogWorkerErrorV2, build_route_catalog_in_worker_v2
from .route_registration import (
    RouteRegistrationClassificationV2,
    RouteSignatureV2,
    materialize_route_registration_v2,
)
from .route_source_artifacts import (
    RouteSourceArtifactErrorV2,
    RouteSourceArtifactV2,
    source_artifacts_for_target_v2,
    source_fingerprint_from_artifacts_v2,
    validate_source_artifacts_v2,
)

_ROOT = Path(__file__).resolve().parents[4]
BUILTIN_ROUTE_CONTRACT_CATALOG_PATH_V2 = _ROOT / "shared/catalogs/builtin-http-route-rows.v2.json"
_DEFAULT_INVENTORY_PATH_V2 = _ROOT / INVENTORY_PATH
_DIGEST_PREFIX_V2 = "sha256:"
_MISSING_V2 = object()
_EXCLUDED_RUNTIME_ROUTE_ROWS_V2 = MappingProxyType(
    {"http-route-capabilities": "lifespan:explicit-exclusion"}
)


class BuiltinRouteContractCatalogErrorV2(RuntimeError):
    """Raised when inventory or generated route-row contracts drift."""


@dataclass(frozen=True, kw_only=True)
class BuiltinRouteInventoryEntryV2:
    row_id: str
    kind: str
    expression: str
    module: str
    prefix: str | None
    line: int

    def to_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "row_id": self.row_id,
            "kind": self.kind,
            "expression": self.expression,
            "module": self.module,
            "line": self.line,
        }
        if self.prefix is not None:
            payload["prefix"] = self.prefix
        return payload


@dataclass(frozen=True, kw_only=True)
class BuiltinRouteInventoryV2:
    schema_version: int
    source: str
    digest: str
    entries: tuple[BuiltinRouteInventoryEntryV2, ...]


@dataclass(frozen=True, kw_only=True)
class RouteRowContributionV2:
    path: str
    name: str
    methods: tuple[str, ...]
    metadata_digest: str

    @classmethod
    def from_signature(cls, signature: RouteSignatureV2) -> RouteRowContributionV2:
        return cls(
            path=signature.path,
            name=signature.name,
            methods=signature.methods,
            metadata_digest=signature.metadata_digest,
        )

    @classmethod
    def from_payload(cls, payload: object, *, row_id: str) -> RouteRowContributionV2:
        if not isinstance(payload, dict):
            raise BuiltinRouteContractCatalogErrorV2(
                f"catalog row {row_id} route signature must be an object"
            )
        path = payload.get("path")
        name = payload.get("name")
        methods = payload.get("methods")
        if not isinstance(path, str) or not path.startswith("/"):
            raise BuiltinRouteContractCatalogErrorV2(
                f"catalog row {row_id} route path must start with /"
            )
        if not isinstance(name, str) or not name:
            raise BuiltinRouteContractCatalogErrorV2(
                f"catalog row {row_id} route name must be non-empty"
            )
        if not isinstance(methods, list) or not methods:
            raise BuiltinRouteContractCatalogErrorV2(
                f"catalog row {row_id} route methods must be a non-empty array"
            )
        normalized = tuple(str(method) for method in methods)
        if any(method != method.upper() or not method for method in normalized):
            raise BuiltinRouteContractCatalogErrorV2(
                f"catalog row {row_id} route methods must be canonical uppercase"
            )
        metadata_digest = _required_digest_v2(
            payload,
            "metadata_digest",
            context=f"catalog row {row_id} route signature",
        )
        return cls(
            path=path,
            name=name,
            methods=normalized,
            metadata_digest=metadata_digest,
        )

    def to_payload(self) -> dict[str, object]:
        return {
            "path": self.path,
            "name": self.name,
            "methods": list(self.methods),
            "metadata_digest": self.metadata_digest,
        }


@dataclass(frozen=True, kw_only=True)
class BuiltinRouteRowContractV2:
    row_id: str
    inventory_kind: str
    module: str
    expression: str
    prefix: str | None
    runtime_owned: bool
    runtime_ownership_evidence: str
    classification: RouteRegistrationClassificationV2
    source_artifacts: tuple[RouteSourceArtifactV2, ...]
    source_fingerprint: str
    ordered_signatures: tuple[RouteRowContributionV2, ...]
    openapi_digest: str | None
    rejections: tuple[str, ...]
    contract_digest: str

    @classmethod
    def from_payload(  # noqa: C901, PLR0912
        cls,
        payload: object,
    ) -> BuiltinRouteRowContractV2:
        if not isinstance(payload, dict):
            raise BuiltinRouteContractCatalogErrorV2("catalog route row must be an object")
        row_id = _required_string_v2(payload, "row_id", context="catalog row")
        inventory_kind = _required_string_v2(payload, "inventory_kind", context=row_id)
        if inventory_kind not in {"helper", "include_router"}:
            raise BuiltinRouteContractCatalogErrorV2(
                f"catalog row {row_id} has unsupported inventory kind {inventory_kind}"
            )
        module = _required_string_v2(payload, "module", context=row_id)
        expression = _required_string_v2(payload, "expression", context=row_id)
        prefix = payload.get("prefix")
        if prefix is not None and not isinstance(prefix, str):
            raise BuiltinRouteContractCatalogErrorV2(
                f"catalog row {row_id} prefix must be a string or null"
            )
        runtime_owned = payload.get("runtime_owned")
        if not isinstance(runtime_owned, bool):
            raise BuiltinRouteContractCatalogErrorV2(
                f"catalog row {row_id} runtime_owned must be a boolean"
            )
        runtime_ownership_evidence = _required_string_v2(
            payload,
            "runtime_ownership_evidence",
            context=row_id,
        )
        raw_classification = _required_string_v2(payload, "classification", context=row_id)
        try:
            classification = RouteRegistrationClassificationV2(raw_classification)
        except ValueError as exc:
            raise BuiltinRouteContractCatalogErrorV2(
                f"catalog row {row_id} has unsupported classification {raw_classification}"
            ) from exc
        raw_artifacts = payload.get("source_artifacts")
        if not isinstance(raw_artifacts, list) or not raw_artifacts:
            raise BuiltinRouteContractCatalogErrorV2(
                f"catalog row {row_id} source_artifacts must be a non-empty array"
            )
        try:
            source_artifacts = tuple(
                RouteSourceArtifactV2.from_payload(item, row_id=row_id) for item in raw_artifacts
            )
        except RouteSourceArtifactErrorV2 as exc:
            raise BuiltinRouteContractCatalogErrorV2(str(exc)) from exc
        artifact_paths = [artifact.path for artifact in source_artifacts]
        if artifact_paths != sorted(set(artifact_paths)):
            raise BuiltinRouteContractCatalogErrorV2(
                f"catalog row {row_id} source artifact paths must be unique and sorted"
            )
        source_fingerprint = _required_digest_v2(
            payload,
            "source_fingerprint",
            context=row_id,
        )
        raw_signatures = payload.get("ordered_signatures")
        if not isinstance(raw_signatures, list):
            raise BuiltinRouteContractCatalogErrorV2(
                f"catalog row {row_id} ordered_signatures must be an array"
            )
        signatures = tuple(
            RouteRowContributionV2.from_payload(item, row_id=row_id) for item in raw_signatures
        )
        openapi_digest = payload.get("openapi_digest")
        if openapi_digest is not None and not _is_digest_v2(openapi_digest):
            raise BuiltinRouteContractCatalogErrorV2(
                f"catalog row {row_id} openapi_digest must be a sha256 digest or null"
            )
        raw_rejections = payload.get("rejections")
        if not isinstance(raw_rejections, list) or not all(
            isinstance(item, str) and item for item in raw_rejections
        ):
            raise BuiltinRouteContractCatalogErrorV2(
                f"catalog row {row_id} rejections must be a string array"
            )
        contract_digest = _required_digest_v2(payload, "contract_digest", context=row_id)
        row = cls(
            row_id=row_id,
            inventory_kind=inventory_kind,
            module=module,
            expression=expression,
            prefix=prefix,
            runtime_owned=runtime_owned,
            runtime_ownership_evidence=runtime_ownership_evidence,
            classification=classification,
            source_artifacts=source_artifacts,
            source_fingerprint=source_fingerprint,
            ordered_signatures=signatures,
            openapi_digest=cast("str | None", openapi_digest),
            rejections=tuple(cast("list[str]", raw_rejections)),
            contract_digest=contract_digest,
        )
        row._validate_semantics()
        expected_source = source_fingerprint_from_artifacts_v2(
            row_id=row.row_id,
            inventory_kind=row.inventory_kind,
            module=row.module,
            expression=row.expression,
            prefix=row.prefix,
            artifacts=row.source_artifacts,
        )
        if source_fingerprint != expected_source:
            raise BuiltinRouteContractCatalogErrorV2(
                f"catalog row {row_id} source fingerprint mismatch: expected {expected_source}"
            )
        expected = _digest_payload_v2(row.to_contract_payload())
        if contract_digest != expected:
            raise BuiltinRouteContractCatalogErrorV2(
                f"catalog row {row_id} contract digest mismatch: expected {expected}"
            )
        return row

    def _validate_semantics(self) -> None:
        evidence_by_ownership = {
            True: {"route-loader:inventory-owned"},
            False: set(_EXCLUDED_RUNTIME_ROUTE_ROWS_V2.values()),
        }
        if self.runtime_ownership_evidence not in evidence_by_ownership[self.runtime_owned]:
            raise BuiltinRouteContractCatalogErrorV2(
                f"catalog row {self.row_id} runtime ownership evidence is inconsistent"
            )
        routes_only = self.classification is RouteRegistrationClassificationV2.ROUTES_ONLY
        if routes_only and (not self.ordered_signatures or self.openapi_digest is None):
            raise BuiltinRouteContractCatalogErrorV2(
                f"routes-only catalog row {self.row_id} must declare routes and OpenAPI digest"
            )
        if routes_only and self.rejections:
            raise BuiltinRouteContractCatalogErrorV2(
                f"routes-only catalog row {self.row_id} cannot declare rejections"
            )
        if not routes_only and (self.ordered_signatures or self.openapi_digest is not None):
            raise BuiltinRouteContractCatalogErrorV2(
                f"non-pure catalog row {self.row_id} cannot publish route contracts"
            )
        if not routes_only and not self.rejections:
            raise BuiltinRouteContractCatalogErrorV2(
                f"non-pure catalog row {self.row_id} must declare a rejection reason"
            )

    def to_contract_payload(self) -> dict[str, object]:
        return {
            "row_id": self.row_id,
            "inventory_kind": self.inventory_kind,
            "module": self.module,
            "expression": self.expression,
            "prefix": self.prefix,
            "runtime_owned": self.runtime_owned,
            "runtime_ownership_evidence": self.runtime_ownership_evidence,
            "classification": self.classification.value,
            "source_artifacts": [item.to_payload() for item in self.source_artifacts],
            "source_fingerprint": self.source_fingerprint,
            "ordered_signatures": [item.to_payload() for item in self.ordered_signatures],
            "openapi_digest": self.openapi_digest,
            "rejections": list(self.rejections),
        }

    def to_payload(self) -> dict[str, object]:
        return {**self.to_contract_payload(), "contract_digest": self.contract_digest}


@dataclass(frozen=True, kw_only=True)
class BuiltinRouteContractCatalogV2:
    schema_version: int
    inventory_source: str
    inventory_digest: str
    source_fingerprint: str
    runtime_row_count: int
    excluded_row_ids: tuple[str, ...]
    rows: tuple[BuiltinRouteRowContractV2, ...]
    catalog_digest: str

    @classmethod
    def from_payload(cls, payload: object) -> BuiltinRouteContractCatalogV2:
        if not isinstance(payload, dict):
            raise BuiltinRouteContractCatalogErrorV2("route contract catalog must be an object")
        schema_version = payload.get("schema_version")
        if schema_version != 2:
            raise BuiltinRouteContractCatalogErrorV2(
                "route contract catalog schema_version must be 2"
            )
        inventory_source = _required_string_v2(
            payload,
            "inventory_source",
            context="catalog",
        )
        inventory_digest = payload.get("inventory_digest")
        if not isinstance(inventory_digest, str) or len(inventory_digest) != 64:
            raise BuiltinRouteContractCatalogErrorV2(
                "route contract catalog inventory_digest must be 64 hex characters"
            )
        source_fingerprint = _required_digest_v2(
            payload,
            "source_fingerprint",
            context="catalog",
        )
        runtime_row_count = payload.get("runtime_row_count")
        if not isinstance(runtime_row_count, int) or runtime_row_count < 0:
            raise BuiltinRouteContractCatalogErrorV2(
                "route contract catalog runtime_row_count must be a non-negative integer"
            )
        raw_excluded = payload.get("excluded_row_ids")
        if not isinstance(raw_excluded, list) or not all(
            isinstance(item, str) and item for item in raw_excluded
        ):
            raise BuiltinRouteContractCatalogErrorV2(
                "route contract catalog excluded_row_ids must be a string array"
            )
        raw_rows = payload.get("rows")
        if not isinstance(raw_rows, list):
            raise BuiltinRouteContractCatalogErrorV2("route contract catalog rows must be an array")
        raw_ids = [item.get("row_id") if isinstance(item, dict) else None for item in raw_rows]
        duplicates = sorted(
            row_id for row_id in set(raw_ids) if row_id is not None and raw_ids.count(row_id) > 1
        )
        if duplicates:
            raise BuiltinRouteContractCatalogErrorV2(
                "duplicate catalog row: " + ", ".join(str(item) for item in duplicates)
            )
        rows = tuple(BuiltinRouteRowContractV2.from_payload(item) for item in raw_rows)
        catalog_digest = _required_digest_v2(payload, "catalog_digest", context="catalog")
        catalog = cls(
            schema_version=2,
            inventory_source=inventory_source,
            inventory_digest=inventory_digest,
            source_fingerprint=source_fingerprint,
            runtime_row_count=runtime_row_count,
            excluded_row_ids=tuple(cast("list[str]", raw_excluded)),
            rows=rows,
            catalog_digest=catalog_digest,
        )
        expected_runtime = sum(row.runtime_owned for row in rows)
        expected_excluded = tuple(row.row_id for row in rows if not row.runtime_owned)
        if runtime_row_count != expected_runtime or catalog.excluded_row_ids != expected_excluded:
            raise BuiltinRouteContractCatalogErrorV2(
                "route contract catalog runtime ownership summary does not match rows"
            )
        expected_source = _catalog_source_fingerprint_v2(rows)
        if source_fingerprint != expected_source:
            raise BuiltinRouteContractCatalogErrorV2(
                f"route catalog source fingerprint mismatch: expected {expected_source}"
            )
        expected_digest = _digest_payload_v2(catalog.to_contract_payload())
        if catalog_digest != expected_digest:
            raise BuiltinRouteContractCatalogErrorV2(
                f"route catalog digest mismatch: expected {expected_digest}"
            )
        return catalog

    def to_contract_payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "inventory_source": self.inventory_source,
            "inventory_digest": self.inventory_digest,
            "source_fingerprint": self.source_fingerprint,
            "runtime_row_count": self.runtime_row_count,
            "excluded_row_ids": list(self.excluded_row_ids),
            "rows": [row.to_payload() for row in self.rows],
        }

    def to_payload(self) -> dict[str, object]:
        return {**self.to_contract_payload(), "catalog_digest": self.catalog_digest}

    @property
    def runtime_rows(self) -> tuple[BuiltinRouteRowContractV2, ...]:
        return tuple(row for row in self.rows if row.runtime_owned)

    def runtime_row(self, row_id: str) -> BuiltinRouteRowContractV2:
        if row_id in self.excluded_row_ids:
            raise BuiltinRouteContractCatalogErrorV2(
                f"route contract catalog row {row_id} is explicitly excluded from runtime"
            )
        return self.row(row_id)

    def row(self, row_id: str) -> BuiltinRouteRowContractV2:
        try:
            return next(row for row in self.rows if row.row_id == row_id)
        except StopIteration as exc:
            raise BuiltinRouteContractCatalogErrorV2(
                f"route contract catalog has no row {row_id}"
            ) from exc


def load_builtin_route_inventory_v2(
    inventory_path: Path = _DEFAULT_INVENTORY_PATH_V2,
) -> BuiltinRouteInventoryV2:
    """Load and digest-check the frozen V1 authority before importing route code."""
    try:
        payload = json.loads(inventory_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BuiltinRouteContractCatalogErrorV2(
            f"cannot load builtin route inventory {inventory_path}: {exc}"
        ) from exc
    if not isinstance(payload, dict):
        raise BuiltinRouteContractCatalogErrorV2("builtin route inventory must be an object")
    if payload.get("schemaVersion") != 1:
        raise BuiltinRouteContractCatalogErrorV2("builtin route inventory schemaVersion must be 1")
    source = payload.get("source")
    digest = payload.get("digest")
    raw_entries = payload.get("entries")
    if not isinstance(source, str) or not source:
        raise BuiltinRouteContractCatalogErrorV2("builtin route inventory source is missing")
    if not isinstance(digest, str) or len(digest) != 64:
        raise BuiltinRouteContractCatalogErrorV2("builtin route inventory digest is invalid")
    if not isinstance(raw_entries, list):
        raise BuiltinRouteContractCatalogErrorV2("builtin route inventory entries must be an array")
    expected = hashlib.sha256(
        json.dumps(raw_entries, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    if digest != expected:
        raise BuiltinRouteContractCatalogErrorV2(f"inventory digest mismatch: expected {expected}")
    entries = tuple(_inventory_entry_from_payload_v2(item) for item in raw_entries)
    ids = [entry.row_id for entry in entries]
    duplicates = sorted(row_id for row_id in set(ids) if ids.count(row_id) > 1)
    if duplicates:
        raise BuiltinRouteContractCatalogErrorV2(
            "duplicate inventory row: " + ", ".join(duplicates)
        )
    missing_exclusions = sorted(set(_EXCLUDED_RUNTIME_ROUTE_ROWS_V2) - set(ids))
    if missing_exclusions:
        raise BuiltinRouteContractCatalogErrorV2(
            "explicit runtime exclusions are absent from inventory: "
            + ", ".join(missing_exclusions)
        )
    return BuiltinRouteInventoryV2(
        schema_version=1,
        source=source,
        digest=digest,
        entries=entries,
    )


def build_builtin_route_contract_catalog_v2(
    *,
    inventory_path: Path = _DEFAULT_INVENTORY_PATH_V2,
) -> BuiltinRouteContractCatalogV2:
    """Generate contracts in a spawned worker so import-time effects cannot leak."""
    _ = load_builtin_route_inventory_v2(inventory_path)
    try:
        payload = build_route_catalog_in_worker_v2(inventory_path)
    except RouteCatalogWorkerErrorV2 as exc:
        raise BuiltinRouteContractCatalogErrorV2(str(exc)) from exc
    return BuiltinRouteContractCatalogV2.from_payload(payload)


def _build_builtin_route_contract_catalog_in_process_v2(  # pyright: ignore[reportUnusedFunction]
    inventory_path: Path,
) -> BuiltinRouteContractCatalogV2:
    """Worker-local catalog generation; never call from a production host process."""
    inventory = load_builtin_route_inventory_v2(inventory_path)
    rows: list[BuiltinRouteRowContractV2] = []
    for entry in inventory.entries:
        target = _resolve_builtin_route_inventory_target_v2(entry)
        source_artifacts = source_artifacts_for_target_v2(target, root=_ROOT)
        materialization = materialize_route_registration_v2(
            kind=entry.kind,
            target=target,
            prefix=entry.prefix,
        )
        unsigned = BuiltinRouteRowContractV2(
            row_id=entry.row_id,
            inventory_kind=entry.kind,
            module=entry.module,
            expression=entry.expression,
            prefix=entry.prefix,
            runtime_owned=_is_runtime_owned_route_row_v2(entry),
            runtime_ownership_evidence=_runtime_ownership_evidence_v2(entry),
            classification=materialization.classification,
            source_artifacts=source_artifacts,
            source_fingerprint=source_fingerprint_from_artifacts_v2(
                row_id=entry.row_id,
                inventory_kind=entry.kind,
                module=entry.module,
                expression=entry.expression,
                prefix=entry.prefix,
                artifacts=source_artifacts,
            ),
            ordered_signatures=tuple(
                RouteRowContributionV2.from_signature(item)
                for item in materialization.ordered_signatures
            ),
            openapi_digest=materialization.openapi_digest,
            rejections=materialization.rejections,
            contract_digest="",
        )
        rows.append(
            replace(
                unsigned,
                contract_digest=_digest_payload_v2(unsigned.to_contract_payload()),
            )
        )
    frozen_rows = tuple(rows)
    source_fingerprint = _catalog_source_fingerprint_v2(frozen_rows)
    unsigned_catalog = BuiltinRouteContractCatalogV2(
        schema_version=2,
        inventory_source=inventory.source,
        inventory_digest=inventory.digest,
        source_fingerprint=source_fingerprint,
        runtime_row_count=sum(row.runtime_owned for row in frozen_rows),
        excluded_row_ids=tuple(row.row_id for row in frozen_rows if not row.runtime_owned),
        rows=frozen_rows,
        catalog_digest="",
    )
    return replace(
        unsigned_catalog,
        catalog_digest=_digest_payload_v2(unsigned_catalog.to_contract_payload()),
    )


def load_builtin_route_contract_catalog_v2(
    *,
    catalog_path: Path = BUILTIN_ROUTE_CONTRACT_CATALOG_PATH_V2,
    inventory_path: Path = _DEFAULT_INVENTORY_PATH_V2,
) -> BuiltinRouteContractCatalogV2:
    """Load a generated catalog and prove exact identity with the frozen inventory."""
    inventory = load_builtin_route_inventory_v2(inventory_path)
    try:
        payload = json.loads(catalog_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BuiltinRouteContractCatalogErrorV2(
            f"cannot load builtin route contract catalog {catalog_path}: {exc}"
        ) from exc
    catalog = BuiltinRouteContractCatalogV2.from_payload(payload)
    if catalog.inventory_source != inventory.source:
        raise BuiltinRouteContractCatalogErrorV2(
            "route catalog inventory source does not match frozen authority"
        )
    if catalog.inventory_digest != inventory.digest:
        raise BuiltinRouteContractCatalogErrorV2(
            "route catalog inventory digest does not match frozen authority"
        )
    try:
        validate_source_artifacts_v2(
            tuple((row.row_id, row.source_artifacts) for row in catalog.rows),
            root=_ROOT,
        )
    except RouteSourceArtifactErrorV2 as exc:
        raise BuiltinRouteContractCatalogErrorV2(str(exc)) from exc
    expected_rows = [entry.row_id for entry in inventory.entries]
    actual_rows = [row.row_id for row in catalog.rows]
    if actual_rows != expected_rows:
        raise BuiltinRouteContractCatalogErrorV2(
            "route catalog rows do not match frozen inventory order"
        )
    for entry, row in zip(inventory.entries, catalog.rows, strict=True):
        expected_identity = (entry.kind, entry.module, entry.expression, entry.prefix)
        actual_identity = (row.inventory_kind, row.module, row.expression, row.prefix)
        if actual_identity != expected_identity:
            raise BuiltinRouteContractCatalogErrorV2(
                f"route catalog row {row.row_id} owner does not match frozen inventory"
            )
    return catalog


def _resolve_builtin_route_inventory_target_v2(entry: BuiltinRouteInventoryEntryV2) -> object:
    """Resolve an inventory target without invoking router factories or helpers."""
    try:
        if entry.kind == "helper" or entry.expression.endswith("()"):
            return _resolve_dotted_v2(entry.module)
        if "." in entry.expression:
            owner = importlib.import_module(entry.module)
            return getattr(owner, entry.expression.rsplit(".", maxsplit=1)[1])
        resolved = _resolve_dotted_v2(entry.module)
        return resolved.router if isinstance(resolved, ModuleType) else resolved
    except (AttributeError, ImportError, TypeError) as exc:
        raise BuiltinRouteContractCatalogErrorV2(
            f"cannot resolve route inventory row {entry.row_id}: {exc}"
        ) from exc


def _is_runtime_owned_route_row_v2(
    entry: BuiltinRouteInventoryEntryV2,
) -> bool:
    """Apply the explicit route-loader/lifespan ownership boundary."""
    return entry.row_id not in _EXCLUDED_RUNTIME_ROUTE_ROWS_V2


def _runtime_ownership_evidence_v2(
    entry: BuiltinRouteInventoryEntryV2,
) -> str:
    return _EXCLUDED_RUNTIME_ROUTE_ROWS_V2.get(
        entry.row_id,
        "route-loader:inventory-owned",
    )


def _inventory_entry_from_payload_v2(payload: object) -> BuiltinRouteInventoryEntryV2:
    if not isinstance(payload, dict):
        raise BuiltinRouteContractCatalogErrorV2("builtin route inventory row must be an object")
    row_id = _required_string_v2(payload, "row_id", context="inventory row")
    kind = _required_string_v2(payload, "kind", context=row_id)
    if kind not in {"helper", "include_router"}:
        raise BuiltinRouteContractCatalogErrorV2(
            f"inventory row {row_id} has unsupported kind {kind}"
        )
    expression = _required_string_v2(payload, "expression", context=row_id)
    module = _required_string_v2(payload, "module", context=row_id)
    prefix = payload.get("prefix")
    line = payload.get("line")
    if prefix is not None and not isinstance(prefix, str):
        raise BuiltinRouteContractCatalogErrorV2(f"inventory row {row_id} prefix must be a string")
    if not isinstance(line, int) or line <= 0:
        raise BuiltinRouteContractCatalogErrorV2(
            f"inventory row {row_id} line must be a positive integer"
        )
    return BuiltinRouteInventoryEntryV2(
        row_id=row_id,
        kind=kind,
        expression=expression,
        module=module,
        prefix=prefix,
        line=line,
    )


def _resolve_dotted_v2(dotted: str) -> object:
    parts = dotted.split(".")
    for cut in range(len(parts), 0, -1):
        module_name = ".".join(parts[:cut])
        try:
            resolved: object = importlib.import_module(module_name)
        except ImportError as exc:
            if getattr(exc, "name", None) == module_name:
                continue
            raise
        for attribute in parts[cut:]:
            resolved = getattr(resolved, attribute)
        return resolved
    raise BuiltinRouteContractCatalogErrorV2(f"cannot import any prefix of {dotted}")


def _catalog_source_fingerprint_v2(
    rows: Sequence[BuiltinRouteRowContractV2],
) -> str:
    return _digest_payload_v2(
        [{"row_id": row.row_id, "source_fingerprint": row.source_fingerprint} for row in rows]
    )


def _digest_payload_v2(payload: object) -> str:
    canonical = rfc8785.dumps(cast("Any", payload))
    return _DIGEST_PREFIX_V2 + hashlib.sha256(canonical).hexdigest()


def _required_string_v2(
    payload: Mapping[str, object],
    field: str,
    *,
    context: str,
) -> str:
    value = payload.get(field, _MISSING_V2)
    if not isinstance(value, str) or not value:
        raise BuiltinRouteContractCatalogErrorV2(f"{context} {field} must be a non-empty string")
    return value


def _required_digest_v2(
    payload: Mapping[str, object],
    field: str,
    *,
    context: str,
) -> str:
    value = payload.get(field, _MISSING_V2)
    if not _is_digest_v2(value):
        raise BuiltinRouteContractCatalogErrorV2(f"{context} {field} must be a sha256 digest")
    return cast("str", value)


def _is_digest_v2(value: object) -> bool:
    if not isinstance(value, str) or not value.startswith(_DIGEST_PREFIX_V2):
        return False
    digest = value.removeprefix(_DIGEST_PREFIX_V2)
    return len(digest) == 64 and all(character in "0123456789abcdef" for character in digest)


__all__ = [
    "BUILTIN_ROUTE_CONTRACT_CATALOG_PATH_V2",
    "BuiltinRouteContractCatalogErrorV2",
    "BuiltinRouteContractCatalogV2",
    "BuiltinRouteInventoryEntryV2",
    "BuiltinRouteInventoryV2",
    "BuiltinRouteRowContractV2",
    "RouteRowContributionV2",
    "RouteSourceArtifactV2",
    "build_builtin_route_contract_catalog_v2",
    "load_builtin_route_contract_catalog_v2",
    "load_builtin_route_inventory_v2",
]
