"""Strict parsing and RFC 8785 canonicalization for plugin protocol v2."""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from enum import Enum
from pathlib import Path
from typing import Any, NoReturn, cast

import jsonschema
import rfc8785

from src.domain.model.plugins.generated_v2 import (
    ArtifactReferenceV2,
    ControlPlaneEnvelopeV2,
    DataPlaneTargetV2,
    PluginManifestV2,
    PluginModuleV2,
    ProfileEntryV2,
    ProfileSnapshotV2,
    QuotaV2,
    RestartPolicyV2,
    RuntimeKindV2,
    ScopeKindV2,
    ScopeV2,
    TrustKindV2,
)

PLUGIN_PROFILE_TYPE_URL_V2 = "types.memstack.ai/plugin.profile.v2"
type JsonValueV2 = None | bool | int | float | str | list["JsonValueV2"] | dict[str, "JsonValueV2"]
_REQUIRED_NULL_FIELDS = {
    "applied_digest",
    "applied_version",
    "error_code",
    "error_message",
    "parent_entry_id",
}
_SCHEMA_PATH = (
    Path(__file__).resolve().parents[4]
    / "shared/schemas/plugins/platform-plugin-protocol.v2.schema.json"
)


class PluginProtocolV2Error(ValueError):
    """A stable protocol rejection with a machine-readable error code."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


def canonical_json_v2(value: object) -> bytes:
    """Return RFC 8785 canonical JSON bytes for a JSON-compatible value."""
    try:
        return rfc8785.dumps(cast(Any, value))
    except (rfc8785.CanonicalizationError, TypeError, ValueError) as exc:
        raise PluginProtocolV2Error("canonical_json_invalid", str(exc)) from exc


def parse_profile_snapshot_v2(payload: object) -> ProfileSnapshotV2:
    """Validate and parse one v2 snapshot; v1 is intentionally rejected."""
    if not isinstance(payload, dict):
        raise PluginProtocolV2Error("invalid_snapshot", "snapshot must be an object")
    if payload.get("schema_version") != 2:
        raise PluginProtocolV2Error(
            "incompatible_schema_version",
            "plugin snapshot schema_version must be 2; v1 is not accepted",
        )
    _validate_schema("ProfileSnapshotV2", payload)
    _validate_snapshot_semantics(payload)
    expected_digest = _snapshot_digest(payload)
    if payload["digest"] != expected_digest:
        raise PluginProtocolV2Error(
            "digest_mismatch",
            f"snapshot digest mismatch: expected {expected_digest}",
        )
    return _snapshot_from_payload(payload)


def parse_plugin_manifest_v2(payload: object) -> PluginManifestV2:
    """Validate and parse one standalone v2 manifest; v1 is not accepted."""
    if not isinstance(payload, dict):
        raise PluginProtocolV2Error("invalid_manifest", "manifest must be an object")
    if payload.get("schema_version") != 2:
        raise PluginProtocolV2Error(
            "incompatible_schema_version",
            "plugin manifest schema_version must be 2; v1 is not accepted",
        )
    _validate_schema("PluginManifestV2", payload)
    module_refs = [item["module_ref"] for item in payload["modules"]]
    if len(module_refs) != len(set(module_refs)):
        raise PluginProtocolV2Error(
            "duplicate_module_ref",
            f"plugin {payload['plugin_id']} declares duplicate module_ref",
        )
    return _manifest_from_payload(payload)


def build_profile_snapshot_v2(
    *,
    profile_id: str,
    generation: int,
    manifests: Sequence[PluginManifestV2],
    entries: Sequence[ProfileEntryV2],
) -> ProfileSnapshotV2:
    """Build a validated snapshot and derive its content digest."""
    payload: dict[str, Any] = {
        "schema_version": 2,
        "profile_id": profile_id,
        "generation": generation,
        "manifests": [_json_value(asdict(manifest)) for manifest in manifests],
        "entries": [_json_value(asdict(entry)) for entry in entries],
    }
    payload["digest"] = hashlib.sha256(canonical_json_v2(payload)).hexdigest()
    return parse_profile_snapshot_v2(payload)


def control_envelope_v2(
    snapshot: ProfileSnapshotV2,
    *,
    version: int,
    nonce: str | None = None,
) -> ControlPlaneEnvelopeV2:
    """Build the only envelope accepted by a protocol v2 data plane."""
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise PluginProtocolV2Error("invalid_version", "version must be a positive integer")
    return ControlPlaneEnvelopeV2(
        version=version,
        nonce=nonce or str(uuid.uuid4()),
        snapshot_digest=snapshot.digest,
        type_url=PLUGIN_PROFILE_TYPE_URL_V2,
    )


def profile_snapshot_v2_to_payload(snapshot: ProfileSnapshotV2) -> dict[str, Any]:
    """Return the complete JSON-compatible snapshot representation."""
    return cast(dict[str, Any], _json_value(asdict(snapshot)))


def _schema() -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(_SCHEMA_PATH.read_text(encoding="utf-8")))


def _validate_schema(definition_name: str, payload: object) -> None:
    schema = _schema()
    scoped_schema = {
        "$schema": schema["$schema"],
        "$defs": schema["$defs"],
        "$ref": f"#/$defs/{definition_name}",
    }
    validator = jsonschema.Draft202012Validator(scoped_schema)
    errors = sorted(
        validator.iter_errors(cast(Any, payload)),
        key=lambda item: list(item.absolute_path),
    )
    if errors:
        error = errors[0]
        location = ".".join(str(item) for item in error.absolute_path) or "$"
        raise PluginProtocolV2Error(
            "schema_validation_failed",
            f"{location}: {error.message}",
        )


def _validate_snapshot_semantics(payload: Mapping[str, Any]) -> None:
    manifests = payload["manifests"]
    entries = payload["entries"]
    manifest_by_id = _unique_by(manifests, "plugin_id", "duplicate_plugin_id")
    entry_by_id = _unique_by(entries, "entry_id", "duplicate_entry_id")

    modules_by_plugin: dict[str, dict[str, Mapping[str, Any]]] = {}
    for plugin_id, manifest in manifest_by_id.items():
        modules = {module["module_ref"]: module for module in manifest["modules"]}
        if len(modules) != len(manifest["modules"]):
            _fail("duplicate_module_ref", f"plugin {plugin_id} declares duplicate module_ref")
        modules_by_plugin[plugin_id] = modules

    for entry_id, entry in entry_by_id.items():
        plugin_ref = entry["plugin_ref"]
        if plugin_ref not in manifest_by_id:
            _fail("missing_manifest", f"entry {entry_id} references missing plugin {plugin_ref}")
        if entry["module_ref"] not in modules_by_plugin.get(plugin_ref, {}):
            _fail(
                "missing_module",
                f"entry {entry_id} references module outside plugin {plugin_ref}",
            )
        parent_id = entry["parent_entry_id"]
        if parent_id is not None and parent_id not in entry_by_id:
            _fail("missing_parent_entry", f"entry {entry_id} has missing parent {parent_id}")
        _validate_scope(entry_id, entry["scope"])

    _validate_parent_tree(entry_by_id)
    for entry_id, entry in entry_by_id.items():
        parent_id = entry["parent_entry_id"]
        if parent_id is None:
            continue
        parent = entry_by_id[parent_id]
        if not _scope_contains(parent["scope"], entry["scope"]):
            _fail(
                "invalid_parent_scope",
                f"entry {entry_id} scope is outside parent {parent_id}",
            )
        child_targets = set(modules_by_plugin[entry["plugin_ref"]][entry["module_ref"]]["targets"])
        parent_targets = set(
            modules_by_plugin[parent["plugin_ref"]][parent["module_ref"]]["targets"]
        )
        if not child_targets.issubset(parent_targets):
            _fail(
                "invalid_parent_targets",
                f"entry {entry_id} targets are outside parent {parent_id}",
            )


def _unique_by(
    values: Sequence[Mapping[str, Any]],
    key: str,
    error_code: str,
) -> dict[str, Mapping[str, Any]]:
    result: dict[str, Mapping[str, Any]] = {}
    for value in values:
        identifier = value[key]
        if identifier in result:
            _fail(error_code, f"duplicate {key}: {identifier}")
        result[identifier] = value
    return result


def _validate_scope(entry_id: str, scope: Mapping[str, Any]) -> None:
    kind = scope["kind"]
    tenant = scope.get("tenant_id")
    project = scope.get("project_id")
    session = scope.get("session_id")
    valid = (
        (kind == "root" and tenant is None and project is None and session is None)
        or (kind == "tenant" and tenant and project is None and session is None)
        or (kind == "project" and tenant and project and session is None)
        or (kind == "session" and tenant and project and session)
    )
    if not valid:
        _fail("invalid_scope", f"entry {entry_id} has inconsistent {kind} scope identifiers")


def _validate_parent_tree(entries: Mapping[str, Mapping[str, Any]]) -> None:
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(entry_id: str) -> None:
        if entry_id in visited:
            return
        if entry_id in visiting:
            _fail("entry_cycle", f"entry parent cycle includes {entry_id}")
        visiting.add(entry_id)
        parent_id = entries[entry_id]["parent_entry_id"]
        if parent_id is not None:
            visit(parent_id)
        visiting.remove(entry_id)
        visited.add(entry_id)

    for entry_id in sorted(entries):
        visit(entry_id)


def _scope_contains(parent: Mapping[str, Any], child: Mapping[str, Any]) -> bool:
    rank = {"root": 0, "tenant": 1, "project": 2, "session": 3}
    if rank[parent["kind"]] > rank[child["kind"]]:
        return False
    for key in ("tenant_id", "project_id", "session_id"):
        parent_value = parent.get(key)
        if parent_value is not None and parent_value != child.get(key):
            return False
    return True


def _snapshot_digest(payload: Mapping[str, Any]) -> str:
    digest_payload = {key: value for key, value in payload.items() if key != "digest"}
    return hashlib.sha256(canonical_json_v2(digest_payload)).hexdigest()


def _snapshot_from_payload(payload: Mapping[str, Any]) -> ProfileSnapshotV2:
    manifests = tuple(_manifest_from_payload(item) for item in payload["manifests"])
    entries = tuple(_entry_from_payload(item) for item in payload["entries"])
    return ProfileSnapshotV2(
        schema_version=2,
        profile_id=payload["profile_id"],
        generation=payload["generation"],
        manifests=manifests,
        entries=entries,
        digest=payload["digest"],
    )


def _manifest_from_payload(payload: Mapping[str, Any]) -> PluginManifestV2:
    modules = tuple(
        PluginModuleV2(
            module_ref=item["module_ref"],
            entrypoint=item["entrypoint"],
            artifact=ArtifactReferenceV2(**item["artifact"]),
            targets=tuple(DataPlaneTargetV2(target) for target in item["targets"]),
        )
        for item in payload["modules"]
    )
    return PluginManifestV2(
        schema_version=2,
        plugin_id=payload["plugin_id"],
        version=payload["version"],
        runtime=RuntimeKindV2(payload["runtime"]),
        trust=TrustKindV2(payload["trust"]),
        modules=modules,
        permissions=tuple(payload["permissions"]),
        quotas=QuotaV2(**payload["quotas"]),
    )


def _entry_from_payload(payload: Mapping[str, Any]) -> ProfileEntryV2:
    return ProfileEntryV2(
        entry_id=payload["entry_id"],
        parent_entry_id=payload["parent_entry_id"],
        plugin_ref=payload["plugin_ref"],
        module_ref=payload["module_ref"],
        enabled=payload["enabled"],
        config=dict(payload["config"]),
        inject=dict(payload["inject"]),
        isolate=dict(payload["isolate"]),
        scope=ScopeV2(
            kind=ScopeKindV2(payload["scope"]["kind"]),
            tenant_id=payload["scope"].get("tenant_id"),
            project_id=payload["scope"].get("project_id"),
            session_id=payload["scope"].get("session_id"),
        ),
        permissions=tuple(payload["permissions"]),
        quotas=QuotaV2(**payload["quotas"]),
        restart_policy=RestartPolicyV2(payload["restart_policy"]),
    )


def _json_value(value: object) -> JsonValueV2:
    if isinstance(value, Enum):
        return cast(JsonValueV2, value.value)
    if isinstance(value, Mapping):
        return {
            str(key): _json_value(item)
            for key, item in value.items()
            if item is not None or str(key) in _REQUIRED_NULL_FIELDS
        }
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return cast(JsonValueV2, value)


def _fail(code: str, message: str) -> NoReturn:
    raise PluginProtocolV2Error(code, message)
