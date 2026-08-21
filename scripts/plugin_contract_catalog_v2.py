"""Build and validate generated protocol-v2 contract catalogs and graphs."""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING, Any, cast

import jsonschema
import rfc8785

if TYPE_CHECKING:
    from collections.abc import Sequence

JSON_SCHEMA_DIALECT_V2 = "https://json-schema.org/draft/2020-12/schema"
_CONTRACT_DIGEST_PREFIX = "sha256:"
_MISSING = object()


def sha256_digest_v2(value: object) -> str:
    """Return the RFC 8785 based digest used by v2 contract artifacts."""
    canonical = rfc8785.dumps(cast("Any", value))
    return _CONTRACT_DIGEST_PREFIX + hashlib.sha256(canonical).hexdigest()


def contract_digest_v2(contract: dict[str, Any]) -> str:
    """Return one module contract's canonical digest."""
    return sha256_digest_v2(contract)


def _validate_json_schema_v2(
    schema: object,
    *,
    context: str,
    require_object: bool = False,
) -> None:
    if not isinstance(schema, dict):
        raise ValueError(f"{context} must be a JSON Schema object")
    if schema.get("$schema") != JSON_SCHEMA_DIALECT_V2:
        raise ValueError(f"{context} must declare JSON Schema draft 2020-12")
    if require_object and schema.get("type") != "object":
        raise ValueError(f"{context} must describe an object")
    try:
        jsonschema.Draft202012Validator.check_schema(schema)
    except jsonschema.SchemaError as exc:
        raise ValueError(f"{context} is not a valid draft 2020-12 schema: {exc.message}") from exc

    def visit(value: object, path: tuple[str, ...]) -> None:
        if isinstance(value, dict):
            if "default" in value:
                raise ValueError(f"{context} forbids default at {'.'.join(path) or '$'}")
            reference = value.get("$ref")
            if reference is not None and (
                not isinstance(reference, str) or not reference.startswith("#/")
            ):
                raise ValueError(f"{context} forbids remote $ref at {'.'.join(path) or '$'}")
            for key, child in value.items():
                visit(child, (*path, str(key)))
        elif isinstance(value, list):
            for index, child in enumerate(value):
                visit(child, (*path, str(index)))

    visit(schema, ())


def _validate_contract_v2(module_ref: str, contract: object) -> dict[str, Any]:
    if not isinstance(contract, dict):
        raise ValueError(f"module {module_ref} contract must be an object")
    services = contract.get("services")
    events = contract.get("events")
    if not isinstance(services, dict) or not isinstance(events, dict):
        raise ValueError(f"module {module_ref} contract services/events must be objects")

    provided = services.get("provides")
    required = services.get("requires")
    emitted = events.get("emits")
    handled = events.get("handles")
    declarations = (provided, required, emitted, handled)
    if not all(isinstance(items, list) for items in declarations):
        raise ValueError(f"module {module_ref} contract declarations must be arrays")

    provided_items = cast("list[dict[str, Any]]", provided)
    required_items = cast("list[dict[str, Any]]", required)
    emitted_items = cast("list[dict[str, Any]]", emitted)
    handled_items = cast("list[dict[str, Any]]", handled)
    key_sets: tuple[tuple[str, list[object]], ...] = (
        ("provided service", [(item["service"], item["version"]) for item in provided_items]),
        ("required service alias", [item["alias"] for item in required_items]),
        ("emitted event", [(item["event"], item["mode"]) for item in emitted_items]),
        ("handled event", [(item["event"], item["mode"]) for item in handled_items]),
    )
    for label, keys in key_sets:
        if len(keys) != len(set(keys)):
            raise ValueError(f"module {module_ref} declares duplicate {label}")

    _validate_json_schema_v2(
        contract.get("config_schema"),
        context=f"module {module_ref} config_schema",
        require_object=True,
    )
    for direction, event_items in (("emits", emitted_items), ("handles", handled_items)):
        for declaration in event_items:
            event = declaration["event"]
            for schema_name in ("payload_schema", "result_schema"):
                _validate_json_schema_v2(
                    declaration[schema_name],
                    context=f"module {module_ref} {direction} {event} {schema_name}",
                )
    return contract


def validate_manifest_contracts_v2(
    manifest: dict[str, Any],
    protocol_schema: dict[str, Any],
) -> None:
    """Validate one manifest schema, public contract schemas, and all digests."""
    owner = f"{manifest.get('plugin_id', '<unknown>')}@{manifest.get('version', '<unknown>')}"
    scoped_schema = {
        "$schema": protocol_schema["$schema"],
        "$defs": protocol_schema["$defs"],
        "$ref": "#/$defs/PluginManifestV2",
    }
    errors = sorted(
        jsonschema.Draft202012Validator(scoped_schema).iter_errors(manifest),
        key=lambda item: list(item.absolute_path),
    )
    if errors:
        error = errors[0]
        location = ".".join(str(item) for item in error.absolute_path) or "$"
        raise ValueError(f"plugin manifest {owner} {location}: {error.message}")

    seen_module_refs: set[str] = set()
    for module in manifest["modules"]:
        module_ref = module["module_ref"]
        if module_ref in seen_module_refs:
            raise ValueError(f"plugin manifest {owner} declares duplicate module {module_ref}")
        seen_module_refs.add(module_ref)
        contract = _validate_contract_v2(module_ref, module["contract"])
        expected_digest = contract_digest_v2(contract)
        if module["contract_digest"] != expected_digest:
            raise ValueError(
                f"module {module_ref} contract digest mismatch: expected {expected_digest}"
            )


def validate_manifest_collection_v2(
    manifests: Sequence[dict[str, Any]],
    protocol_schema: dict[str, Any],
) -> None:
    """Validate a non-empty manifest collection and its cross-manifest graphs."""
    if not manifests:
        raise ValueError("manifest collection must not be empty")
    for manifest in manifests:
        validate_manifest_contracts_v2(manifest, protocol_schema)
    _ = _ordered_manifest_modules_v2(manifests)
    _ = build_service_graph_v2(manifests)
    _ = build_event_graph_v2(manifests)


def _ordered_manifest_modules_v2(
    manifests: Sequence[dict[str, Any]],
) -> tuple[tuple[dict[str, Any], dict[str, Any]], ...]:
    rows: list[tuple[dict[str, Any], dict[str, Any]]] = []
    owners: dict[str, str] = {}
    for manifest in manifests:
        plugin_id = manifest.get("plugin_id")
        plugin_version = manifest.get("version")
        modules = manifest.get("modules")
        if not isinstance(plugin_id, str) or not isinstance(plugin_version, str):
            raise ValueError("manifest collection requires string plugin_id and version")
        if not isinstance(modules, list):
            raise ValueError(f"manifest {plugin_id}@{plugin_version} modules must be an array")
        owner = f"{plugin_id}@{plugin_version}"
        for raw_module in modules:
            if not isinstance(raw_module, dict) or not isinstance(
                raw_module.get("module_ref"), str
            ):
                raise ValueError(f"manifest {owner} contains an invalid module_ref")
            module = cast("dict[str, Any]", raw_module)
            module_ref = cast("str", module["module_ref"])
            previous = owners.get(module_ref)
            if previous is not None:
                raise ValueError(
                    f"manifest collection declares duplicate module_ref {module_ref}: "
                    f"{previous} and {owner}"
                )
            owners[module_ref] = owner
            rows.append((manifest, module))
    return tuple(sorted(rows, key=lambda item: item[1]["module_ref"]))


def build_catalog_v2(manifests: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Build the normalized, language-neutral module catalog."""
    modules = [
        {
            "plugin_id": manifest["plugin_id"],
            "plugin_version": manifest["version"],
            "module_ref": module["module_ref"],
            "entrypoint": module["entrypoint"],
            "artifact_digest": module["artifact"]["digest"],
            "targets": sorted(module["targets"]),
            "contract": module["contract"],
            "contract_digest": module["contract_digest"],
        }
        for manifest, module in _ordered_manifest_modules_v2(manifests)
    ]
    document: dict[str, Any] = {"schema_version": 2, "modules": modules}
    document["catalog_digest"] = sha256_digest_v2(document)
    return document


def build_service_graph_v2(manifests: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Build exact-version provider/consumer nodes and candidate dependency edges."""
    module_rows = _ordered_manifest_modules_v2(manifests)
    providers: dict[tuple[str, str], list[str]] = {}
    nodes: list[dict[str, Any]] = []
    for _manifest, module in module_rows:
        module_ref = module["module_ref"]
        services = module["contract"]["services"]
        for item in services["provides"]:
            key = (item["service"], item["version"])
            providers.setdefault(key, []).append(module_ref)
            nodes.append(
                {
                    "module_ref": module_ref,
                    "role": "provider",
                    "service": item["service"],
                    "version": item["version"],
                }
            )
        for item in services["requires"]:
            nodes.append(
                {
                    "alias": item["alias"],
                    "module_ref": module_ref,
                    "role": "consumer",
                    "service": item["service"],
                    "version": item["version"],
                }
            )

    edges: list[dict[str, Any]] = []
    for _manifest, module in module_rows:
        consumer_ref = module["module_ref"]
        for item in module["contract"]["services"]["requires"]:
            matches = providers.get((item["service"], item["version"]), [])
            if not matches:
                raise ValueError(
                    f"module {consumer_ref} requires missing {item['service']}@{item['version']}"
                )
            edges.extend(
                {
                    "alias": item["alias"],
                    "consumer_module_ref": consumer_ref,
                    "provider_module_ref": provider_ref,
                    "service": item["service"],
                    "version": item["version"],
                }
                for provider_ref in matches
            )
    node_key = lambda item: (  # noqa: E731 - local deterministic sort key
        item["module_ref"],
        item["role"],
        item["service"],
        item.get("alias", ""),
    )
    edge_key = lambda item: (  # noqa: E731 - local deterministic sort key
        item["consumer_module_ref"],
        item["provider_module_ref"],
        item["alias"],
    )
    return {
        "schema_version": 2,
        "nodes": sorted(nodes, key=node_key),
        "edges": sorted(edges, key=edge_key),
    }


def build_event_graph_v2(manifests: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Build fixed-mode event nodes and exact-schema emitter/handler edges."""
    module_rows = _ordered_manifest_modules_v2(manifests)
    nodes: list[dict[str, Any]] = []
    registries: dict[str, dict[tuple[str, str, str, str], list[str]]] = {
        "emitter": {},
        "handler": {},
    }
    event_contracts: dict[str, tuple[tuple[str, str, str], str]] = {}
    for _manifest, module in module_rows:
        module_ref = module["module_ref"]
        for role, direction in (("emitter", "emits"), ("handler", "handles")):
            for item in module["contract"]["events"][direction]:
                payload_digest = sha256_digest_v2(item["payload_schema"])
                result_digest = sha256_digest_v2(item["result_schema"])
                signature = (item["mode"], payload_digest, result_digest)
                previous = event_contracts.get(item["event"])
                if previous is not None and previous[0] != signature:
                    raise ValueError(
                        f"event {item['event']} contract conflict between "
                        f"{previous[1]} and {module_ref}"
                    )
                event_contracts[item["event"]] = (signature, module_ref)
                key = (item["event"], item["mode"], payload_digest, result_digest)
                registries[role].setdefault(key, []).append(module_ref)
                nodes.append(
                    {
                        "event": item["event"],
                        "mode": item["mode"],
                        "module_ref": module_ref,
                        "payload_schema_digest": payload_digest,
                        "result_schema_digest": result_digest,
                        "role": role,
                    }
                )
    edges = [
        {
            "emitter_module_ref": emitter_ref,
            "event": key[0],
            "handler_module_ref": handler_ref,
            "mode": key[1],
            "payload_schema_digest": key[2],
            "result_schema_digest": key[3],
        }
        for key, emitter_refs in registries["emitter"].items()
        for emitter_ref in emitter_refs
        for handler_ref in registries["handler"].get(key, [])
    ]
    node_key = lambda item: (  # noqa: E731 - local deterministic sort key
        item["event"],
        item["mode"],
        item["role"],
        item["module_ref"],
    )
    edge_key = lambda item: (  # noqa: E731 - local deterministic sort key
        item["event"],
        item["mode"],
        item["emitter_module_ref"],
        item["handler_module_ref"],
    )
    return {
        "schema_version": 2,
        "nodes": sorted(nodes, key=node_key),
        "edges": sorted(edges, key=edge_key),
    }


def _mutation_case(
    name: str,
    operation: str,
    path: str,
    expected_error: str,
    *,
    value: object = _MISSING,
    refresh_digest: bool = False,
) -> dict[str, Any]:
    mutation: dict[str, Any] = {"operation": operation, "path": path}
    if value is not _MISSING:
        mutation["value"] = value
    if refresh_digest:
        mutation["refresh_contract_digest"] = True
    return {"name": name, "mutation": mutation, "expected_error": expected_error}


def build_contract_conformance_fixture_v2(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Build shared positive and negative contract validation vectors."""
    manifest = cast("dict[str, Any]", snapshot["manifests"][0])
    modules = manifest["modules"]
    contract_root = "/manifests/0/modules"
    negatives = [
        _mutation_case(
            "contract-digest-mismatch",
            "replace",
            f"{contract_root}/0/contract_digest",
            "contract_digest_mismatch",
            value=f"sha256:{'0' * 64}",
        ),
        _mutation_case(
            "config-default-forbidden",
            "add",
            f"{contract_root}/0/contract/config_schema/properties/label/default",
            "invalid_contract_schema",
            value="root",
        ),
        _mutation_case(
            "config-remote-ref-forbidden",
            "add",
            f"{contract_root}/0/contract/config_schema/properties/label/$ref",
            "invalid_contract_schema",
            value="https://example.invalid/label.schema.json",
        ),
        _mutation_case(
            "invalid-config-before-apply",
            "replace",
            "/entries/0/config/label",
            "invalid_module_config",
            value="",
        ),
        _mutation_case(
            "missing-required-inject",
            "remove",
            "/entries/1/inject/clock",
            "missing_required_inject",
        ),
        _mutation_case(
            "unexpected-inject",
            "add",
            "/entries/0/inject/clock",
            "unexpected_inject",
            value="service:clock",
        ),
        _mutation_case(
            "required-service-version-mismatch",
            "replace",
            f"{contract_root}/1/contract/services/requires/0/version",
            "service_version_mismatch",
            value="2.0.0",
            refresh_digest=True,
        ),
        {
            "name": "provider-conflict-same-scope-isolation",
            "mutation": {
                "operations": [
                    {
                        "operation": "add",
                        "path": f"{contract_root}/1/contract/services/provides/0",
                        "value": {"service": "service:clock", "version": "1.0.0"},
                    },
                    {
                        "operation": "replace",
                        "path": "/entries/1/scope",
                        "value": {"kind": "root"},
                    },
                ],
                "refresh_contract_digest": True,
            },
            "expected_error": "provider_conflict",
        },
        _mutation_case(
            "event-mode-mismatch",
            "replace",
            f"{contract_root}/1/contract/events/emits/0/mode",
            "event_contract_mismatch",
            value="serial",
            refresh_digest=True,
        ),
    ]
    completeness = [
        ("builtin://conformance/root-provider", "provide", "service:undeclared"),
        ("builtin://conformance/session-consumer", "require", "undeclared_alias"),
        ("builtin://conformance/root-provider", "on", "undeclared-event"),
        ("builtin://conformance/session-consumer", "dispatch", "undeclared-event"),
    ]
    return {
        "schema_version": 2,
        "positive": {
            "contracts": [
                {
                    "contract": module["contract"],
                    "contract_digest": module["contract_digest"],
                    "module_ref": module["module_ref"],
                }
                for module in modules
            ],
            "service_graph": build_service_graph_v2((manifest,)),
            "event_graph": build_event_graph_v2((manifest,)),
        },
        "negative_cases": negatives,
        "runtime_completeness_cases": [
            {
                "module_ref": module_ref,
                "operation": operation,
                "name": name,
                "expected_error": f"undeclared_{'event_handler' if operation == 'on' else 'event_dispatch' if operation == 'dispatch' else operation}",
            }
            for module_ref, operation, name in completeness
        ],
    }


__all__ = [
    "JSON_SCHEMA_DIALECT_V2",
    "build_catalog_v2",
    "build_contract_conformance_fixture_v2",
    "build_event_graph_v2",
    "build_service_graph_v2",
    "contract_digest_v2",
    "sha256_digest_v2",
    "validate_manifest_collection_v2",
    "validate_manifest_contracts_v2",
]
