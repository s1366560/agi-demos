#!/usr/bin/env python3
"""Generate v2 plugin protocol DTOs from the authoritative JSON Schema."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import rfc8785

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

if TYPE_CHECKING:
    from scripts.plugin_contract_catalog_v2 import (
        JSON_SCHEMA_DIALECT_V2,
        build_catalog_v2,
        build_contract_conformance_fixture_v2,
        build_event_graph_v2,
        build_service_graph_v2,
        contract_digest_v2,
        validate_manifest_collection_v2,
    )
elif __package__:
    from .plugin_contract_catalog_v2 import (
        JSON_SCHEMA_DIALECT_V2,
        build_catalog_v2,
        build_contract_conformance_fixture_v2,
        build_event_graph_v2,
        build_service_graph_v2,
        contract_digest_v2,
        validate_manifest_collection_v2,
    )
else:
    from plugin_contract_catalog_v2 import (
        JSON_SCHEMA_DIALECT_V2,
        build_catalog_v2,
        build_contract_conformance_fixture_v2,
        build_event_graph_v2,
        build_service_graph_v2,
        contract_digest_v2,
        validate_manifest_collection_v2,
    )

SCHEMA_PATH = ROOT / "shared/schemas/plugins/platform-plugin-protocol.v2.schema.json"
PYTHON_PATH = ROOT / "src/domain/model/plugins/generated_v2.py"
RUST_PATH = ROOT / "agi-stack/crates/plugin-host/src/protocol_v2/generated.rs"
TYPESCRIPT_PATH = ROOT / "agi-stack/packages/plugin-runtime/src/generated.ts"
SNAPSHOT_FIXTURE_PATH = ROOT / "shared/fixtures/platform-plugin-profile.v2.json"
CONFORMANCE_FIXTURE_PATH = ROOT / "shared/fixtures/plugin-runtime-conformance.v2.json"
CONTRACT_CONFORMANCE_FIXTURE_PATH = ROOT / "shared/fixtures/plugin-contract-conformance.v2.json"
BUILTIN_MANIFEST_DIRECTORY = ROOT / "config/plugin-manifests-v2"
SHARED_CATALOG_PATH = ROOT / "shared/catalogs/plugin-module-catalog.v2.json"
PYTHON_CATALOG_PATH = ROOT / "src/domain/model/plugins/generated_catalog_v2.py"
RUST_CATALOG_PATH = ROOT / "agi-stack/crates/plugin-host/src/protocol_v2/generated_catalog.rs"
TYPESCRIPT_CATALOG_PATH = ROOT / "agi-stack/packages/plugin-runtime/src/generatedCatalog.ts"
SERVICE_GRAPH_PATH = ROOT / "shared/graphs/plugin-service-dependencies.v2.json"
EVENT_GRAPH_PATH = ROOT / "shared/graphs/plugin-events.v2.json"
DEFAULT_PROFILE_PATH = ROOT / "config/plugin-profiles/memstack-default.v2.yaml"
BOOTSTRAP_PROFILE_PATH = ROOT / "shared/profiles/memstack-default-bootstrap.v2.json"
_CONFORMANCE_ARTIFACT_BYTES_V2 = b"memstack-plugin-runtime-v2-test-artifact\n"


def _schema() -> dict[str, Any]:
    return cast("dict[str, Any]", json.loads(SCHEMA_PATH.read_text(encoding="utf-8")))


def _ref_name(value: str) -> str:
    prefix = "#/$defs/"
    if not value.startswith(prefix):
        raise ValueError(f"unsupported external schema reference: {value}")
    return value.removeprefix(prefix)


def _nullable(schema: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    raw_type = schema.get("type")
    if not isinstance(raw_type, list) or "null" not in raw_type:
        return schema, False
    non_null = [item for item in raw_type if item != "null"]
    if len(non_null) != 1:
        raise ValueError(f"unsupported nullable type: {raw_type}")
    return {**schema, "type": non_null[0]}, True


def _python_type(schema: dict[str, Any]) -> str:
    normalized, nullable = _nullable(schema)
    if "$ref" in normalized:
        result = _ref_name(normalized["$ref"])
    else:
        raw_type = normalized.get("type")
        if raw_type == "string":
            result = "str"
        elif raw_type == "integer":
            result = "int"
        elif raw_type == "boolean":
            result = "bool"
        elif raw_type == "array":
            result = f"tuple[{_python_type(normalized['items'])}, ...]"
        elif raw_type == "object":
            additional = normalized.get("additionalProperties")
            value_type = _python_type(additional) if isinstance(additional, dict) else "Any"
            result = f"Mapping[str, {value_type}]"
        else:
            raise ValueError(f"unsupported Python schema: {normalized}")
    return f"{result} | None" if nullable else result


def _rust_type(schema: dict[str, Any]) -> str:
    normalized, nullable = _nullable(schema)
    if "$ref" in normalized:
        result = _ref_name(normalized["$ref"])
    else:
        raw_type = normalized.get("type")
        if raw_type == "string":
            result = "String"
        elif raw_type == "integer":
            result = "u64"
        elif raw_type == "boolean":
            result = "bool"
        elif raw_type == "array":
            result = f"Vec<{_rust_type(normalized['items'])}>"
        elif raw_type == "object":
            additional = normalized.get("additionalProperties")
            value_type = (
                _rust_type(additional) if isinstance(additional, dict) else "serde_json::Value"
            )
            result = f"BTreeMap<String, {value_type}>"
        else:
            raise ValueError(f"unsupported Rust schema: {normalized}")
    return f"Option<{result}>" if nullable else result


def _typescript_type(schema: dict[str, Any]) -> str:
    normalized, nullable = _nullable(schema)
    if "$ref" in normalized:
        result = _ref_name(normalized["$ref"])
    else:
        raw_type = normalized.get("type")
        if raw_type == "string":
            result = "string"
        elif raw_type == "integer":
            result = "number"
        elif raw_type == "boolean":
            result = "boolean"
        elif raw_type == "array":
            result = f"ReadonlyArray<{_typescript_type(normalized['items'])}>"
        elif raw_type == "object":
            additional = normalized.get("additionalProperties")
            value_type = _typescript_type(additional) if isinstance(additional, dict) else "unknown"
            result = f"Readonly<Record<string, {value_type}>>"
        else:
            raise ValueError(f"unsupported TypeScript schema: {normalized}")
    return f"{result} | null" if nullable else result


def _header(comment: str, schema_hash: str) -> list[str]:
    return [
        f"{comment} Generated from shared/schemas/plugins/platform-plugin-protocol.v2.schema.json.",
        f"{comment} Schema SHA-256: {schema_hash}",
        f"{comment} Do not edit by hand; run scripts/generate_plugin_protocol_v2.py.",
        "",
    ]


def _generate_python(definitions: dict[str, Any], schema_hash: str) -> str:
    lines = _header("#", schema_hash)
    lines.extend(
        [
            "from __future__ import annotations",
            "",
            "from collections.abc import Mapping",
            "from dataclasses import dataclass",
            "from enum import StrEnum",
            "from typing import Any",
            "",
            "",
        ]
    )
    exported: list[str] = []
    for name, definition in definitions.items():
        exported.append(name)
        if name == "JsonSchemaV2":
            lines.extend(["JsonSchemaV2 = Mapping[str, Any]", "", ""])
            continue
        if definition.get("type") == "string" and "enum" in definition:
            lines.append(f"class {name}(StrEnum):")
            for value in definition["enum"]:
                member = str(value).upper().replace("-", "_")
                lines.append(f"    {member} = {json.dumps(value)}")
            lines.append("")
            lines.append("")
            continue
        if definition.get("type") != "object":
            continue
        required = set(definition.get("required", []))
        lines.extend(["@dataclass(frozen=True, kw_only=True)", f"class {name}:"])
        properties = definition.get("properties", {})
        if not properties:
            lines.append("    pass")
        for field_name, field_schema in properties.items():
            annotation = _python_type(field_schema)
            if field_name not in required and "None" not in annotation:
                annotation = f"{annotation} | None"
            default = "" if field_name in required else " = None"
            lines.append(f"    {field_name}: {annotation}{default}")
        lines.append("")
        lines.append("")
    lines.append("__all__ = [")
    lines.extend(f"    {json.dumps(name)}," for name in sorted(exported))
    lines.append("]")
    lines.append("")
    return "\n".join(lines)


def _generate_rust(definitions: dict[str, Any], schema_hash: str) -> str:
    lines = _header("//", schema_hash)
    lines.extend(
        [
            "use std::collections::BTreeMap;",
            "",
            "use serde::{Deserialize, Serialize};",
            "",
        ]
    )
    for name, definition in definitions.items():
        if name == "JsonSchemaV2":
            lines.extend(
                [
                    "pub type JsonSchemaV2 = BTreeMap<String, serde_json::Value>;",
                    "",
                ]
            )
            continue
        if definition.get("type") == "string" and "enum" in definition:
            lines.extend(
                [
                    "#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]",
                    '#[serde(rename_all = "kebab-case")]',
                    f"pub enum {name} {{",
                ]
            )
            for value in definition["enum"]:
                variant = "".join(part.title() for part in str(value).replace("-", "_").split("_"))
                lines.append(f"    {variant},")
            lines.extend(["}", ""])
            continue
        if definition.get("type") != "object":
            continue
        required = set(definition.get("required", []))
        lines.extend(
            [
                "#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]",
                "#[serde(deny_unknown_fields)]",
                f"pub struct {name} {{",
            ]
        )
        for field_name, field_schema in definition.get("properties", {}).items():
            annotation = _rust_type(field_schema)
            optional = field_name not in required
            if optional and not annotation.startswith("Option<"):
                annotation = f"Option<{annotation}>"
            if optional:
                lines.append('    #[serde(default, skip_serializing_if = "Option::is_none")]')
            lines.append(f"    pub {field_name}: {annotation},")
        lines.extend(["}", ""])
    return "\n".join(lines)


def _generate_typescript(definitions: dict[str, Any], schema_hash: str) -> str:
    lines = _header("//", schema_hash)
    for name, definition in definitions.items():
        if name == "JsonSchemaV2":
            lines.extend(
                [
                    "export type JsonSchemaV2 = Readonly<Record<string, unknown>>;",
                    "",
                ]
            )
            continue
        if definition.get("type") == "string" and "enum" in definition:
            values = [_typescript_string(value) for value in definition["enum"]]
            declaration = f"export type {name} = {' | '.join(values)};"
            if len(declaration) <= 100:
                lines.extend([declaration, ""])
            else:
                lines.append(f"export type {name} =")
                lines.extend(
                    f"  | {value}{';' if index == len(values) - 1 else ''}"
                    for index, value in enumerate(values)
                )
                lines.append("")
            continue
        if definition.get("type") != "object":
            continue
        required = set(definition.get("required", []))
        lines.append(f"export interface {name} {{")
        for field_name, field_schema in definition.get("properties", {}).items():
            optional = "" if field_name in required else "?"
            lines.append(f"  readonly {field_name}{optional}: {_typescript_type(field_schema)};")
        lines.extend(["}", ""])
    return "\n".join(lines)


def _typescript_string(value: str) -> str:
    escaped = (
        value.replace("\\", "\\\\").replace("'", "\\'").replace("\r", "\\r").replace("\n", "\\n")
    )
    return f"'{escaped}'"


def _canonical_document(value: object) -> str:
    return rfc8785.dumps(cast("Any", value)).decode("utf-8") + "\n"


def _builtin_manifest(
    schema: dict[str, Any],
    *,
    artifact_root: Path | None = ROOT,
) -> tuple[dict[str, Any], ...]:
    manifest_paths = sorted(BUILTIN_MANIFEST_DIRECTORY.glob("*.json"), key=lambda path: path.name)
    if not manifest_paths:
        raise ValueError(f"no protocol-v2 manifests found in {BUILTIN_MANIFEST_DIRECTORY}")
    manifests: list[dict[str, Any]] = []
    for path in manifest_paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError(f"protocol-v2 manifest must be an object: {path}")
        manifests.append(cast("dict[str, Any]", payload))
    validate_manifest_collection_v2(manifests, schema, artifact_root=artifact_root)
    return tuple(manifests)


def _string_chunks(value: str, *, width: int = 88) -> list[str]:
    return [value[index : index + width] for index in range(0, len(value), width)] or [""]


def _generate_python_catalog(catalog: dict[str, Any], schema_hash: str) -> str:
    canonical = _canonical_document(catalog)
    lines = _header("#", schema_hash)
    lines.extend(["from typing import Final", ""])
    lines.append("# fmt: off")
    lines.append("PLUGIN_MODULE_CATALOG_V2_JSON: Final[str] = (")
    lines.extend(f"    {chunk!r}" for chunk in _string_chunks(canonical))
    lines.extend(
        [
            ")",
            "PLUGIN_MODULE_CATALOG_DIGEST_V2: Final[str] = (",
            f"    {json.dumps(catalog['catalog_digest'])}",
            ")",
            "# fmt: on",
            "",
            '__all__ = ["PLUGIN_MODULE_CATALOG_DIGEST_V2", "PLUGIN_MODULE_CATALOG_V2_JSON"]',
            "",
        ]
    )
    return "\n".join(lines)


def _generate_rust_catalog(catalog: dict[str, Any], schema_hash: str) -> str:
    canonical = _canonical_document(catalog)
    lines = _header("//", schema_hash)
    lines.append("pub const PLUGIN_MODULE_CATALOG_V2_JSON: &str = concat!(")
    lines.extend(
        f"    {json.dumps(chunk, ensure_ascii=False)}," for chunk in _string_chunks(canonical)
    )
    lines.extend(
        [
            ");",
            "pub const PLUGIN_MODULE_CATALOG_DIGEST_V2: &str =",
            f'    "{catalog["catalog_digest"]}";',
            "",
        ]
    )
    return "\n".join(lines)


def _generate_typescript_catalog(catalog: dict[str, Any], schema_hash: str) -> str:
    canonical = _canonical_document(catalog)
    lines = _header("//", schema_hash)
    lines.extend(
        [
            "import type { DataPlaneTargetV2, PluginContractV2 } from './generated';",
            "",
            "export interface PluginModuleCatalogEntryV2 {",
            "  readonly artifact_digest: string;",
            "  readonly artifact_source: string;",
            "  readonly contract: PluginContractV2;",
            "  readonly contract_digest: string;",
            "  readonly entrypoint: string;",
            "  readonly module_ref: string;",
            "  readonly plugin_id: string;",
            "  readonly plugin_version: string;",
            "  readonly targets: ReadonlyArray<DataPlaneTargetV2>;",
            "}",
            "",
            "export interface PluginModuleCatalogV2 {",
            "  readonly catalog_digest: string;",
            "  readonly modules: ReadonlyArray<PluginModuleCatalogEntryV2>;",
            "  readonly schema_version: 2;",
            "}",
            "",
            "export const PLUGIN_MODULE_CATALOG_V2_JSON = [",
        ]
    )
    lines.extend(f"  {_typescript_string(chunk)}," for chunk in _string_chunks(canonical, width=84))
    lines.extend(
        [
            "].join('');",
            "",
            "export const PLUGIN_MODULE_CATALOG_V2 = JSON.parse(",
            "  PLUGIN_MODULE_CATALOG_V2_JSON",
            ") as PluginModuleCatalogV2;",
            "",
            "export const PLUGIN_MODULE_CATALOG_DIGEST_V2 =",
            f"  '{catalog['catalog_digest']}' as const;",
            "",
        ]
    )
    return "\n".join(lines)


def _snapshot_fixture() -> dict[str, Any]:
    artifact = {
        "digest": f"sha256:{hashlib.sha256(_CONFORMANCE_ARTIFACT_BYTES_V2).hexdigest()}",
        "source": "fixture://plugin-runtime-conformance-v2",
    }
    nullable_object_schema = {
        "$schema": JSON_SCHEMA_DIALECT_V2,
        "type": ["object", "null"],
    }
    nullable_string_schema = {
        "$schema": JSON_SCHEMA_DIALECT_V2,
        "type": ["string", "null"],
    }
    integer_schema = {"$schema": JSON_SCHEMA_DIALECT_V2, "type": "integer"}
    object_schema = {"$schema": JSON_SCHEMA_DIALECT_V2, "type": "object"}
    array_schema = {"$schema": JSON_SCHEMA_DIALECT_V2, "type": "array"}
    emit_event = {
        "event": "notify",
        "mode": "emit",
        "payload_schema": object_schema,
        "result_schema": array_schema,
    }
    serial_event = {
        "event": "audit",
        "mode": "serial",
        "payload_schema": object_schema,
        "result_schema": array_schema,
    }
    choose_event = {
        "event": "choose",
        "mode": "bail",
        "payload_schema": nullable_object_schema,
        "result_schema": nullable_string_schema,
    }
    transform_event = {
        "event": "transform",
        "mode": "waterfall",
        "payload_schema": integer_schema,
        "result_schema": integer_schema,
    }
    root_contract = {
        "services": {
            "provides": [{"service": "service:clock", "version": "1.0.0"}],
            "requires": [],
        },
        "events": {
            "emits": [],
            "handles": [emit_event, serial_event, choose_event, transform_event],
        },
        "config_schema": {
            "$schema": JSON_SCHEMA_DIALECT_V2,
            "type": "object",
            "additionalProperties": False,
            "required": ["label"],
            "properties": {"label": {"type": "string", "minLength": 1}},
        },
    }
    consumer_contract = {
        "services": {
            "provides": [],
            "requires": [{"alias": "clock", "service": "service:clock", "version": "1.0.0"}],
        },
        "events": {
            "emits": [emit_event, serial_event, choose_event, transform_event],
            "handles": [],
        },
        "config_schema": {
            "$schema": JSON_SCHEMA_DIALECT_V2,
            "type": "object",
            "additionalProperties": False,
            "required": ["temperature"],
            "properties": {"temperature": {"type": "number", "minimum": 0, "maximum": 2}},
        },
    }
    payload: dict[str, Any] = {
        "schema_version": 2,
        "profile_id": "conformance-v2",
        "generation": 7,
        "manifests": [
            {
                "schema_version": 2,
                "plugin_id": "conformance-v2",
                "version": "1.0.0",
                "runtime": "python-trusted",
                "trust": "builtin",
                "modules": [
                    {
                        "module_ref": "builtin://conformance/root-provider",
                        "entrypoint": "conformance:root_provider",
                        "artifact": artifact,
                        "targets": ["python", "rust-server", "web"],
                        "contract": root_contract,
                        "contract_digest": contract_digest_v2(root_contract),
                    },
                    {
                        "module_ref": "builtin://conformance/session-consumer",
                        "entrypoint": "conformance:session_consumer",
                        "artifact": artifact,
                        "targets": ["python", "rust-server", "web"],
                        "contract": consumer_contract,
                        "contract_digest": contract_digest_v2(consumer_contract),
                    },
                ],
                "permissions": ["service.clock.read"],
                "quotas": {"max_concurrent_calls": 4},
            }
        ],
        "entries": [
            {
                "entry_id": "root-provider",
                "parent_entry_id": None,
                "plugin_ref": "conformance-v2",
                "module_ref": "builtin://conformance/root-provider",
                "enabled": True,
                "config": {"label": "根"},
                "inject": {},
                "isolate": {},
                "scope": {"kind": "root"},
                "permissions": ["service.clock.read"],
                "quotas": {},
                "restart_policy": "hot-generation",
            },
            {
                "entry_id": "session-consumer",
                "parent_entry_id": "root-provider",
                "plugin_ref": "conformance-v2",
                "module_ref": "builtin://conformance/session-consumer",
                "enabled": True,
                "config": {"temperature": 0.7},
                "inject": {"clock": "service:clock"},
                "isolate": {},
                "scope": {
                    "kind": "session",
                    "tenant_id": "tenant-a",
                    "project_id": "project-a",
                    "session_id": "session-a",
                },
                "permissions": [],
                "quotas": {},
                "restart_policy": "hot-generation",
            },
        ],
    }
    payload["digest"] = hashlib.sha256(rfc8785.dumps(payload)).hexdigest()
    return payload


def _conformance_fixture(snapshot: dict[str, Any]) -> dict[str, Any]:
    canonical_input = {"z": 1.0, "中文": "值", "a": 2}
    canonical = rfc8785.dumps(cast("Any", canonical_input))
    manifest = cast("dict[str, Any]", snapshot["manifests"][0])
    service_graph = build_service_graph_v2((manifest,))
    event_graph = build_event_graph_v2((manifest,))
    lifecycle_initial = ["provider-apply:10", "consumer-apply:10->10"]
    lifecycle_removed = [
        *lifecycle_initial,
        "consumer-dispose:10",
        "provider-dispose:10",
    ]
    lifecycle_restored = [
        *lifecycle_removed,
        "provider-apply:12",
        "consumer-apply:12->12",
    ]
    return {
        "schema_version": 2,
        "snapshot_digest": snapshot["digest"],
        "canonical_json": [
            {
                "name": "unicode-and-number-normalization",
                "input": canonical_input,
                "expected": canonical.decode("utf-8"),
                "sha256": hashlib.sha256(canonical).hexdigest(),
            }
        ],
        "dependency_order": {
            "expected": ["root-provider", "session-consumer"],
        },
        "contract_digests": {
            module["module_ref"]: module["contract_digest"] for module in manifest["modules"]
        },
        "service_edges": service_graph["edges"],
        "event_edges": event_graph["edges"],
        "target_projection": {
            "python": ["root-provider", "session-consumer"],
            "rust-server": ["root-provider", "session-consumer"],
            "desktop-sidecar": [],
            "web": ["root-provider", "session-consumer"],
            "desktop-renderer": [],
        },
        "scope_lookup": [
            {
                "service": "service:clock",
                "consumer_entry_id": "session-consumer",
                "expected_provider_entry_id": "root-provider",
            }
        ],
        "fiber_transitions": {
            "success": ["pending", "loading", "active", "unloading", "disposed"],
            "failure": ["pending", "loading", "failed"],
        },
        "effect_disposal": {
            "registration": ["provider", "listener", "module"],
            "expected": ["module", "listener", "provider"],
        },
        "provider_generation_lifecycle": {
            "initial_generation": 10,
            "removed_generation": 11,
            "restored_generation": 12,
            "after_initial": lifecycle_initial,
            "after_removal": lifecycle_removed,
            "after_restore": lifecycle_restored,
            "after_close": [
                *lifecycle_restored,
                "consumer-dispose:12",
                "provider-dispose:12",
            ],
        },
        "waterfall": {
            "input": 2,
            "operations": ["add:1", "multiply:2"],
            "expected": 6,
        },
        "reconcile": [
            {"case": "same-version-same-digest", "expected": "ack"},
            {"case": "same-version-new-digest", "expected": "nack"},
            {"case": "stale-version", "expected": "nack"},
            {"case": "failed-staging", "expected": "last-good"},
        ],
    }


def _bootstrap_profile(
    manifests: tuple[dict[str, Any], ...],
    *,
    local_acceptance: bool = False,
    sync_acceptance: bool = False,
    cloud_acceptance: bool = False,
) -> dict[str, Any]:
    from src.infrastructure.plugins.v2.composer import compose_profile_v2, load_profile_document_v2
    from src.infrastructure.plugins.v2.protocol import (
        parse_plugin_manifest_v2,
        profile_snapshot_v2_to_payload,
    )
    from src.infrastructure.plugins.v2.target_profiles import (
        include_production_target_hosts_v2,
    )

    parsed = tuple(parse_plugin_manifest_v2(manifest) for manifest in manifests)
    manifest_by_id = {manifest.plugin_id: manifest for manifest in parsed}
    document = include_production_target_hosts_v2(load_profile_document_v2(DEFAULT_PROFILE_PATH))
    if sum((local_acceptance, sync_acceptance, cloud_acceptance)) > 1:
        raise ValueError("acceptance purposes are mutually exclusive")
    if local_acceptance:
        from scripts.local_knowledge_acceptance_profile import include_local_knowledge_acceptance

        document = include_local_knowledge_acceptance(
            document, ROOT / "config/plugin-profiles/memstack-local-knowledge-acceptance.v2.yaml"
        )
    if sync_acceptance:
        from scripts.knowledge_sync_acceptance_profile import include_knowledge_sync_acceptance

        document = include_knowledge_sync_acceptance(
            document, ROOT / "config/plugin-profiles/memstack-knowledge-sync-acceptance.v2.yaml"
        )
    if cloud_acceptance:
        from scripts.cloud_knowledge_sync_acceptance_profile import (
            include_cloud_knowledge_sync_acceptance,
        )

        document = include_cloud_knowledge_sync_acceptance(
            document,
            ROOT / "config/plugin-profiles/memstack-cloud-knowledge-sync-acceptance.v2.yaml",
        )
    snapshot = compose_profile_v2(
        document,
        manifest_by_id,
        generation=1,
    )
    return profile_snapshot_v2_to_payload(snapshot)


def _cloud_acceptance_generation_vectors(manifests: tuple[dict[str, Any], ...]) -> dict[str, Any]:
    from scripts.cloud_knowledge_sync_acceptance_profile import (
        cloud_knowledge_sync_generation_vectors,
    )
    from src.infrastructure.plugins.v2.protocol import parse_profile_snapshot_v2

    return cloud_knowledge_sync_generation_vectors(
        parse_profile_snapshot_v2(_bootstrap_profile(manifests, cloud_acceptance=True))
    )


def _write_or_check(path: Path, content: str, *, check: bool) -> bool:
    expected = content.encode("utf-8")
    if check:
        if not path.exists() or path.read_bytes() != expected:
            print(f"out of date: {path.relative_to(ROOT)}", file=sys.stderr)
            return False
        return True
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_bytes(expected)
    temporary.replace(path)
    return True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.add_argument(
        "--refresh-artifacts",
        action="append",
        default=[],
        metavar="MODULE_REF",
        help="refresh one explicitly reviewed repository artifact (repeat for multiple modules)",
    )
    args = parser.parse_args()

    schema = _schema()
    definitions = schema["$defs"]
    schema_hash = hashlib.sha256(SCHEMA_PATH.read_bytes()).hexdigest()
    from scripts.refresh_plugin_artifacts_v2 import refresh_declared_artifacts_v2

    _builtin_manifest(schema, artifact_root=None)
    changes = refresh_declared_artifacts_v2(
        ROOT, BUILTIN_MANIFEST_DIRECTORY, frozenset(args.refresh_artifacts), check=args.check
    )
    for change in changes:
        print(json.dumps(change, sort_keys=True))
    manifests = _builtin_manifest(schema)
    catalog = build_catalog_v2(manifests)
    snapshot = _snapshot_fixture()
    outputs = {
        PYTHON_PATH: _generate_python(definitions, schema_hash),
        RUST_PATH: _generate_rust(definitions, schema_hash),
        TYPESCRIPT_PATH: _generate_typescript(definitions, schema_hash),
        SHARED_CATALOG_PATH: _canonical_document(catalog),
        PYTHON_CATALOG_PATH: _generate_python_catalog(catalog, schema_hash),
        RUST_CATALOG_PATH: _generate_rust_catalog(catalog, schema_hash),
        TYPESCRIPT_CATALOG_PATH: _generate_typescript_catalog(catalog, schema_hash),
        SERVICE_GRAPH_PATH: _canonical_document(build_service_graph_v2(manifests)),
        EVENT_GRAPH_PATH: _canonical_document(build_event_graph_v2(manifests)),
        BOOTSTRAP_PROFILE_PATH: _canonical_document(_bootstrap_profile(manifests)),
        ROOT / "shared/profiles/memstack-local-knowledge-acceptance.v2.json": _canonical_document(
            _bootstrap_profile(manifests, local_acceptance=True)
        ),
        ROOT / "shared/profiles/memstack-knowledge-sync-acceptance.v2.json": _canonical_document(
            _bootstrap_profile(manifests, sync_acceptance=True)
        ),
        ROOT
        / "shared/profiles/memstack-cloud-knowledge-sync-acceptance.v2.json": _canonical_document(
            _bootstrap_profile(manifests, cloud_acceptance=True)
        ),
        ROOT
        / "shared/fixtures/cloud-knowledge-sync-acceptance-generations.v1.json": _canonical_document(
            _cloud_acceptance_generation_vectors(manifests)
        ),
        SNAPSHOT_FIXTURE_PATH: _canonical_document(snapshot),
        CONFORMANCE_FIXTURE_PATH: _canonical_document(_conformance_fixture(snapshot)),
        CONTRACT_CONFORMANCE_FIXTURE_PATH: _canonical_document(
            build_contract_conformance_fixture_v2(snapshot)
        ),
    }
    results = [
        _write_or_check(path, content, check=args.check) for path, content in outputs.items()
    ]
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
