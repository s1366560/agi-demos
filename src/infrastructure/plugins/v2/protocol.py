"""Strict parsing and RFC 8785 canonicalization for plugin protocol v2."""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict
from enum import Enum
from pathlib import Path
from typing import Any, NoReturn, cast

import jsonschema
import rfc8785

from src.domain.model.plugins.generated_v2 import (
    ApplyStatusV2,
    ArtifactReferenceV2,
    BundleArtifactV2,
    BundleManifestV2,
    BundleReferenceV2,
    ControlPlaneEnvelopeV2,
    DataPlaneTargetV2,
    DesiredBundleSetV2,
    EventContractsV2,
    EventContractV2,
    EventModeV2,
    PluginContractV2,
    PluginManifestV2,
    PluginModuleV2,
    ProfileEntryV2,
    ProfileLayerKindV2,
    ProfileLayerV2,
    ProfileSnapshotV2,
    ProfileSourceReferenceV2,
    ProfileSourceV2,
    QuotaV2,
    RestartPolicyV2,
    RuntimeKindV2,
    ScopeKindV2,
    ScopeV2,
    ServiceContractV2,
    ServiceProvidedV2,
    ServiceRequiredV2,
    SnapshotApplyReceiptV2,
    TrustKindV2,
)

PLUGIN_PROFILE_TYPE_URL_V2 = "types.memstack.ai/plugin.profile.v2"
JSON_SCHEMA_DIALECT_V2 = "https://json-schema.org/draft/2020-12/schema"
type JsonValueV2 = None | bool | int | float | str | list["JsonValueV2"] | dict[str, "JsonValueV2"]
_REQUIRED_NULL_FIELDS = {
    "applied_digest",
    "applied_version",
    "error_code",
    "error_message",
    "parent_entry_id",
    "provenance",
    "signature",
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


def plugin_contract_digest_v2(contract: PluginContractV2) -> str:
    """Return the normative RFC 8785 digest for one public module contract."""
    payload = _json_value(asdict(contract))
    return f"sha256:{hashlib.sha256(canonical_json_v2(payload)).hexdigest()}"


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
    _validate_manifest_semantics(payload)
    _validate_event_contracts((payload,))
    return _manifest_from_payload(payload)


def parse_bundle_manifest_v2(payload: object) -> BundleManifestV2:
    """Validate and parse one immutable protocol-v2 Bundle manifest."""
    raw = _require_schema_version_v2(payload, kind="bundle manifest")
    _validate_schema("BundleManifestV2", raw)
    manifests = tuple(parse_plugin_manifest_v2(item) for item in raw["manifests"])
    plugin_ids = tuple(manifest.plugin_id for manifest in manifests)
    if len(plugin_ids) != len(set(plugin_ids)):
        _fail("duplicate_plugin_id", "bundle manifest declares a plugin more than once")
    _validate_event_contracts(raw["manifests"])
    layers = tuple(_profile_layer_from_payload(item) for item in raw["layers"])
    layer_ids = tuple(layer.layer_id for layer in layers)
    if len(layer_ids) != len(set(layer_ids)):
        _fail("duplicate_layer_id", "bundle manifest declares a layer more than once")
    artifacts = tuple(
        BundleArtifactV2(
            artifact_id=item["artifact_id"],
            target=DataPlaneTargetV2(item["target"]),
            path=item["path"],
            digest=item["digest"],
            size_bytes=item["size_bytes"],
            media_type=item["media_type"],
        )
        for item in raw["artifacts"]
    )
    _validate_bundle_artifact_inventory_v2(manifests, artifacts)
    bundle = BundleManifestV2(
        schema_version=2,
        bundle_id=raw["bundle_id"],
        version=raw["version"],
        manifests=manifests,
        layers=layers,
        artifacts=artifacts,
        digest=raw["digest"],
        signature=raw["signature"],
        provenance=raw["provenance"],
    )
    from .layer_composer import bundle_manifest_digest_v2

    expected = bundle_manifest_digest_v2(bundle)
    if bundle.digest != expected:
        _fail("bundle_digest_mismatch", f"bundle manifest digest mismatch: expected {expected}")
    return bundle


def parse_profile_source_v2(payload: object) -> ProfileSourceV2:
    """Validate and parse one exact revisioned protocol-v2 ProfileSource."""
    raw = _require_schema_version_v2(payload, kind="profile source")
    _validate_schema("ProfileSourceV2", raw)
    layers = tuple(_profile_layer_from_payload(item) for item in raw["layers"])
    layer_ids = tuple(layer.layer_id for layer in layers)
    if len(layer_ids) != len(set(layer_ids)):
        _fail("duplicate_layer_id", "profile source declares a layer more than once")
    source = ProfileSourceV2(
        schema_version=2,
        source_id=raw["source_id"],
        profile_id=raw["profile_id"],
        revision=raw["revision"],
        digest=raw["digest"],
        provenance=raw["provenance"],
        layers=layers,
    )
    from .layer_composer import profile_source_digest_v2

    expected = profile_source_digest_v2(source)
    if source.digest != expected:
        _fail(
            "profile_source_digest_mismatch", f"profile source digest mismatch: expected {expected}"
        )
    return source


def parse_desired_bundle_set_v2(payload: object) -> DesiredBundleSetV2:
    """Validate and parse one immutable ordered protocol-v2 desired Bundle set."""
    raw = _require_schema_version_v2(payload, kind="desired bundle set")
    _validate_schema("DesiredBundleSetV2", raw)
    bundles = tuple(BundleReferenceV2(**item) for item in raw["bundles"])
    bundle_ids = tuple(reference.bundle_id for reference in bundles)
    if len(bundle_ids) != len(set(bundle_ids)):
        _fail("duplicate_bundle_reference", "desired bundle set repeats a bundle reference")
    desired = DesiredBundleSetV2(
        schema_version=2,
        desired_set_id=raw["desired_set_id"],
        revision=raw["revision"],
        bundles=bundles,
        profile_source=ProfileSourceReferenceV2(**raw["profile_source"]),
        digest=raw["digest"],
    )
    from .layer_composer import desired_bundle_set_digest_v2

    expected = desired_bundle_set_digest_v2(desired)
    if desired.digest != expected:
        _fail(
            "desired_bundle_set_digest_mismatch",
            f"desired bundle set digest mismatch: expected {expected}",
        )
    return desired


def parse_control_envelope_v2(payload: object) -> ControlPlaneEnvelopeV2:
    """Validate and parse the distribution envelope accepted by v2 data planes."""
    if not isinstance(payload, dict):
        raise PluginProtocolV2Error("invalid_envelope", "control envelope must be an object")
    _validate_schema("ControlPlaneEnvelopeV2", payload)
    return ControlPlaneEnvelopeV2(
        version=payload["version"],
        nonce=payload["nonce"],
        snapshot_digest=payload["snapshot_digest"],
        type_url=payload["type_url"],
    )


def parse_snapshot_apply_receipt_v2(payload: object) -> SnapshotApplyReceiptV2:
    """Validate and parse the exact ACK/NACK shape shared by v2 data planes."""
    if not isinstance(payload, dict):
        raise PluginProtocolV2Error("invalid_receipt", "snapshot receipt must be an object")
    raw = cast(dict[str, Any], payload)
    _validate_schema("SnapshotApplyReceiptV2", raw)
    return SnapshotApplyReceiptV2(
        status=ApplyStatusV2(raw["status"]),
        requested_version=raw["requested_version"],
        requested_digest=raw["requested_digest"],
        applied_version=raw["applied_version"],
        applied_digest=raw["applied_digest"],
        error_code=raw["error_code"],
        error_message=raw["error_message"],
    )


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


def control_envelope_v2_to_payload(envelope: ControlPlaneEnvelopeV2) -> dict[str, Any]:
    """Return the complete JSON-compatible control envelope representation."""
    return cast(dict[str, Any], _json_value(asdict(envelope)))


def snapshot_apply_receipt_v2_to_payload(
    receipt: SnapshotApplyReceiptV2,
) -> dict[str, Any]:
    """Return the complete JSON-compatible v2 receipt representation."""
    return cast(dict[str, Any], _json_value(asdict(receipt)))


def bundle_manifest_v2_to_payload(bundle: BundleManifestV2) -> dict[str, Any]:
    """Return the complete JSON-compatible Bundle manifest representation."""
    return cast(dict[str, Any], _json_value(asdict(bundle)))


def profile_source_v2_to_payload(source: ProfileSourceV2) -> dict[str, Any]:
    """Return the complete JSON-compatible ProfileSource representation."""
    return cast(dict[str, Any], _json_value(asdict(source)))


def desired_bundle_set_v2_to_payload(desired: DesiredBundleSetV2) -> dict[str, Any]:
    """Return the complete JSON-compatible DesiredBundleSet representation."""
    return cast(dict[str, Any], _json_value(asdict(desired)))


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
        _validate_manifest_semantics(manifest)
        modules = {module["module_ref"]: module for module in manifest["modules"]}
        if len(modules) != len(manifest["modules"]):
            _fail("duplicate_module_ref", f"plugin {plugin_id} declares duplicate module_ref")
        modules_by_plugin[plugin_id] = modules

    _validate_event_contracts(manifest_by_id.values())

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


def _profile_layer_from_payload(payload: Mapping[str, Any]) -> ProfileLayerV2:
    scope_payload = payload["scope"]
    return ProfileLayerV2(
        layer_id=payload["layer_id"],
        kind=ProfileLayerKindV2(payload["kind"]),
        scope=ScopeV2(
            kind=ScopeKindV2(scope_payload["kind"]),
            tenant_id=scope_payload.get("tenant_id"),
            project_id=scope_payload.get("project_id"),
            session_id=scope_payload.get("session_id"),
        ),
        entries=tuple(_entry_from_payload(item) for item in payload["entries"]),
        replacements=tuple(_entry_from_payload(item) for item in payload["replacements"]),
        disabled_entry_ids=tuple(payload["disabled_entry_ids"]),
    )


def _validate_bundle_artifact_inventory_v2(
    manifests: Sequence[PluginManifestV2],
    artifacts: Sequence[BundleArtifactV2],
) -> None:
    artifact_ids = tuple(artifact.artifact_id for artifact in artifacts)
    if len(artifact_ids) != len(set(artifact_ids)):
        _fail("duplicate_bundle_artifact", "bundle repeats an artifact_id")
    artifact_paths = tuple(artifact.path for artifact in artifacts)
    if len(artifact_paths) != len(set(artifact_paths)):
        _fail("duplicate_bundle_artifact_path", "bundle repeats an artifact path")
    available = {(artifact.target, artifact.digest) for artifact in artifacts}
    required = {
        (target, module.artifact.digest)
        for manifest in manifests
        for module in manifest.modules
        for target in module.targets
    }
    missing = sorted(
        f"{target.value}@{digest}"
        for target, digest in required
        if (target, digest) not in available
    )
    if missing:
        _fail(
            "bundle_artifact_coverage_missing",
            f"bundle has no target artifact for: {', '.join(missing)}",
        )


def _require_schema_version_v2(payload: object, *, kind: str) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise PluginProtocolV2Error(
            f"invalid_{kind.replace(' ', '_')}", f"{kind} must be an object"
        )
    raw = cast(dict[str, Any], payload)
    if raw.get("schema_version") != 2:
        raise PluginProtocolV2Error(
            "incompatible_schema_version",
            f"{kind} schema_version must be 2; v1 is not accepted",
        )
    return raw


def _manifest_from_payload(payload: Mapping[str, Any]) -> PluginManifestV2:
    modules = tuple(
        PluginModuleV2(
            module_ref=item["module_ref"],
            entrypoint=item["entrypoint"],
            artifact=ArtifactReferenceV2(**item["artifact"]),
            targets=tuple(DataPlaneTargetV2(target) for target in item["targets"]),
            contract=_contract_from_payload(item["contract"]),
            contract_digest=item["contract_digest"],
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


def _contract_from_payload(payload: Mapping[str, Any]) -> PluginContractV2:
    services = payload["services"]
    events = payload["events"]
    return PluginContractV2(
        services=ServiceContractV2(
            provides=tuple(ServiceProvidedV2(**item) for item in services["provides"]),
            requires=tuple(ServiceRequiredV2(**item) for item in services["requires"]),
        ),
        events=EventContractsV2(
            emits=tuple(_event_contract_from_payload(item) for item in events["emits"]),
            handles=tuple(_event_contract_from_payload(item) for item in events["handles"]),
        ),
        config_schema=dict(payload["config_schema"]),
    )


def _event_contract_from_payload(payload: Mapping[str, Any]) -> EventContractV2:
    return EventContractV2(
        event=payload["event"],
        mode=EventModeV2(payload["mode"]),
        payload_schema=dict(payload["payload_schema"]),
        result_schema=dict(payload["result_schema"]),
    )


def _validate_manifest_semantics(payload: Mapping[str, Any]) -> None:
    module_refs: set[str] = set()
    for module in payload["modules"]:
        module_ref = module["module_ref"]
        if module_ref in module_refs:
            _fail(
                "duplicate_module_ref",
                f"plugin {payload['plugin_id']} declares duplicate module_ref",
            )
        module_refs.add(module_ref)
        _validate_contract(module_ref, module["contract"], module["contract_digest"])


def _validate_contract(
    module_ref: str,
    contract: Mapping[str, Any],
    declared_digest: str,
) -> None:
    services = contract["services"]
    provided = [(item["service"], item["version"]) for item in services["provides"]]
    required_aliases = [item["alias"] for item in services["requires"]]
    if len(provided) != len(set(provided)):
        _fail("duplicate_service_provision", f"module {module_ref} repeats a provided service")
    if len(required_aliases) != len(set(required_aliases)):
        _fail("duplicate_service_requirement", f"module {module_ref} repeats a required alias")

    _validate_contract_schema(
        contract["config_schema"],
        context=f"module {module_ref} config_schema",
        require_object=True,
    )
    events = contract["events"]
    for direction in ("emits", "handles"):
        names: set[str] = set()
        for event in events[direction]:
            name = event["event"]
            if name in names:
                _fail(
                    "duplicate_event_contract",
                    f"module {module_ref} repeats {direction} event {name}",
                )
            names.add(name)
            _validate_contract_schema(
                event["payload_schema"],
                context=f"module {module_ref} {direction} {name} payload_schema",
            )
            _validate_contract_schema(
                event["result_schema"],
                context=f"module {module_ref} {direction} {name} result_schema",
            )

    expected_digest = f"sha256:{hashlib.sha256(canonical_json_v2(contract)).hexdigest()}"
    if declared_digest != expected_digest:
        _fail(
            "contract_digest_mismatch",
            f"module {module_ref} contract digest mismatch: expected {expected_digest}",
        )


def _validate_contract_schema(
    schema: Mapping[str, Any],
    *,
    context: str,
    require_object: bool = False,
) -> None:
    if schema.get("$schema") != JSON_SCHEMA_DIALECT_V2:
        _fail("invalid_contract_schema", f"{context} must declare JSON Schema draft 2020-12")
    if require_object and schema.get("type") != "object":
        _fail("invalid_contract_schema", f"{context} must describe an object")
    try:
        jsonschema.Draft202012Validator.check_schema(cast(Any, schema))
    except jsonschema.SchemaError as exc:
        _fail("invalid_contract_schema", f"{context}: {exc.message}")

    def visit(value: object, path: tuple[str, ...]) -> None:
        if isinstance(value, Mapping):
            if "default" in value:
                _fail(
                    "invalid_contract_schema",
                    f"{context} forbids default at {'.'.join(path) or '$'}",
                )
            reference = value.get("$ref")
            if reference is not None and (
                not isinstance(reference, str) or not reference.startswith("#/")
            ):
                _fail(
                    "invalid_contract_schema",
                    f"{context} forbids remote $ref at {'.'.join(path) or '$'}",
                )
            for key, child in value.items():
                visit(child, (*path, str(key)))
        elif isinstance(value, list):
            for index, child in enumerate(value):
                visit(child, (*path, str(index)))

    visit(schema, ())


def _validate_event_contracts(manifests: Iterable[Mapping[str, Any]]) -> None:
    declarations: dict[str, tuple[str, bytes, bytes]] = {}
    owners: dict[str, str] = {}
    for manifest in manifests:
        for module in manifest["modules"]:
            for direction in ("emits", "handles"):
                for event in module["contract"]["events"][direction]:
                    signature = (
                        event["mode"],
                        canonical_json_v2(event["payload_schema"]),
                        canonical_json_v2(event["result_schema"]),
                    )
                    previous = declarations.get(event["event"])
                    if previous is not None and previous != signature:
                        _fail(
                            "event_contract_mismatch",
                            f"event {event['event']} differs between "
                            f"{owners[event['event']]} and {module['module_ref']}",
                        )
                    declarations[event["event"]] = signature
                    owners[event["event"]] = module["module_ref"]


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
