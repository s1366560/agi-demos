#!/usr/bin/env python3
"""Generate v2 plugin protocol DTOs from the authoritative JSON Schema."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, cast

import rfc8785

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "shared/schemas/plugins/platform-plugin-protocol.v2.schema.json"
PYTHON_PATH = ROOT / "src/domain/model/plugins/generated_v2.py"
RUST_PATH = ROOT / "agi-stack/crates/plugin-host/src/protocol_v2/generated.rs"
TYPESCRIPT_PATH = ROOT / "agi-stack/packages/plugin-runtime/src/generated.ts"
SNAPSHOT_FIXTURE_PATH = ROOT / "shared/fixtures/platform-plugin-profile.v2.json"
CONFORMANCE_FIXTURE_PATH = ROOT / "shared/fixtures/plugin-runtime-conformance.v2.json"


def _schema() -> dict[str, Any]:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


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
    escaped = value.replace("\\", "\\\\").replace("'", "\\'")
    return f"'{escaped}'"


def _canonical_document(value: object) -> str:
    return rfc8785.dumps(cast(Any, value)).decode("utf-8") + "\n"


def _snapshot_fixture() -> dict[str, Any]:
    artifact = {
        "digest": f"sha256:{'c' * 64}",
        "source": "package://builtin/conformance-v2",
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
                    },
                    {
                        "module_ref": "builtin://conformance/session-consumer",
                        "entrypoint": "conformance:session_consumer",
                        "artifact": artifact,
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
    canonical = rfc8785.dumps(canonical_input)
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
    args = parser.parse_args()

    schema = _schema()
    definitions = schema["$defs"]
    schema_hash = hashlib.sha256(SCHEMA_PATH.read_bytes()).hexdigest()
    snapshot = _snapshot_fixture()
    outputs = {
        PYTHON_PATH: _generate_python(definitions, schema_hash),
        RUST_PATH: _generate_rust(definitions, schema_hash),
        TYPESCRIPT_PATH: _generate_typescript(definitions, schema_hash),
        SNAPSHOT_FIXTURE_PATH: _canonical_document(snapshot),
        CONFORMANCE_FIXTURE_PATH: _canonical_document(_conformance_fixture(snapshot)),
    }
    results = [
        _write_or_check(path, content, check=args.check) for path, content in outputs.items()
    ]
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
